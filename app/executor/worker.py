# app/executor/worker.py
import os
import uuid
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List

from rq import Queue, Worker, Connection
from rq.job import Job
import redis

from app.executor.container import ContainerExecutor
from app.models.agent import Agent
from app.utils.security import validate_agent_code

logger = logging.getLogger(__name__)

class AgentExecutorWorker:
    """
    Worker class that handles agent execution jobs from the Redis Queue.
    """
    
    def __init__(
        self,
        redis_url: str,
        queue_name: str = "agent_executions",
        agent_storage_path: str = "/data/agents",
        container_executor: Optional[ContainerExecutor] = None,
        callback_url: str = "http://api:5000/api/v1",
    ):
        self.redis_url = redis_url
        self.queue_name = queue_name
        self.agent_storage_path = agent_storage_path
        self.callback_url = callback_url
        
        # Redis connection
        self.redis_conn = redis.from_url(redis_url)
        
        # Create container executor if not provided
        self.container_executor = container_executor or ContainerExecutor()
        
        # Create directory for agent storage if it doesn't exist
        os.makedirs(agent_storage_path, exist_ok=True)
    
    def start_worker(self):
        """Start the RQ worker process."""
        with Connection(self.redis_conn):
            worker = Worker(queues=[self.queue_name])
            worker.work(with_scheduler=True)
    
    def queue_execution(
        self,
        agent_id: str,
        user_id: str,
        messages: List[Dict[str, Any]],
        env_vars: Optional[Dict[str, str]] = None,
        user_vars: Optional[Dict[str, Any]] = None,
        parent_execution_id: Optional[str] = None,
        api_key: str = "",
    ) -> str:
        """
        Queue an agent for execution.
        
        Args:
            agent_id: ID of the agent to execute
            user_id: ID of the user requesting execution
            messages: List of message objects in the conversation
            env_vars: Environment variables for the agent (optional)
            user_vars: User-specific variables for the agent (optional)
            parent_execution_id: ID of the parent execution if this is a sub-execution
            api_key: API key for authentication with the callback URL
            
        Returns:
            Execution job ID
        """
        # Generate a unique execution ID
        execution_id = str(uuid.uuid4())
        
        # Create job data
        job_data = {
            "execution_id": execution_id,
            "agent_id": agent_id,
            "user_id": user_id,
            "messages": messages,
            "env_vars": env_vars or {},
            "user_vars": user_vars or {},
            "parent_execution_id": parent_execution_id,
            "api_key": api_key,
            "callback_url": self.callback_url,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Create RQ queue
        queue = Queue(self.queue_name, connection=self.redis_conn)
        
        # Enqueue the job
        job = queue.enqueue(
            self.execute_agent_job,
            job_data,
            job_id=execution_id,
            result_ttl=3600,  # Keep results for 1 hour
            timeout=600,      # 10-minute timeout
        )
        
        logger.info(f"Queued agent execution: {execution_id} for agent {agent_id}")
        return execution_id
    
    def execute_agent_job(self, job_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute an agent job (this runs in the worker process).
        
        Args:
            job_data: Dictionary containing execution data
            
        Returns:
            Dictionary with execution results
        """
        execution_id = job_data["execution_id"]
        agent_id = job_data["agent_id"]
        
        logger.info(f"Starting execution {execution_id} for agent {agent_id}")
        
        try:
            # Get agent code path
            agent_path = os.path.join(self.agent_storage_path, agent_id)
            
            if not os.path.exists(agent_path):
                raise FileNotFoundError(f"Agent code not found for agent ID: {agent_id}")
            
            # Validate agent code for security concerns
            validation_result = validate_agent_code(agent_path)
            if not validation_result["valid"]:
                logger.error(f"Agent code validation failed: {validation_result['reason']}")
                return {
                    "status": "error",
                    "error": f"Agent code validation failed: {validation_result['reason']}"
                }
            
            # Prepare context data for execution
            context_data = {
                "execution_id": execution_id,
                "agent_id": agent_id,
                "user_id": job_data["user_id"],
                "messages": job_data["messages"],
                "env_vars": job_data["env_vars"],
                "user_vars": job_data["user_vars"],
                "callback_url": job_data["callback_url"],
                "api_key": job_data["api_key"],
                "parent_execution_id": job_data.get("parent_execution_id"),
            }
            
            # Execute the agent using the container executor
            execution_results = self.container_executor.execute_agent(
                agent_path,
                context_data
            )
            
            # Send execution results to callback URL
            try:
                import requests
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {job_data['api_key']}"
                }
                
                requests.post(
                    f"{job_data['callback_url']}/executions/{execution_id}/complete",
                    json=execution_results,
                    headers=headers,
                    timeout=10
                )
            except Exception as e:
                logger.error(f"Failed to send execution results callback: {str(e)}")
            
            logger.info(f"Completed execution {execution_id} for agent {agent_id}")
            return execution_results
            
        except Exception as e:
            error_msg = f"Error executing agent {agent_id}: {str(e)}"
            logger.error(error_msg)
            
            error_result = {
                "status": "error",
                "error": error_msg,
                "execution_id": execution_id,
                "agent_id": agent_id
            }
            
            # Try to send error to callback URL
            try:
                import requests
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {job_data['api_key']}"
                }
                
                requests.post(
                    f"{job_data['callback_url']}/executions/{execution_id}/complete",
                    json=error_result,
                    headers=headers,
                    timeout=10
                )
            except Exception:
                pass
                
            return error_result
    
    def get_execution_status(self, execution_id: str) -> Dict[str, Any]:
        """
        Get the status of an execution job.
        
        Args:
            execution_id: ID of the execution job
            
        Returns:
            Dictionary with job status
        """
        try:
            job = Job.fetch(execution_id, connection=self.redis_conn)
            
            status = job.get_status()
            result = job.result if status == "finished" else None
            
            return {
                "execution_id": execution_id,
                "status": status,
                "enqueued_at": job.enqueued_at.isoformat() if job.enqueued_at else None,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "ended_at": job.ended_at.isoformat() if job.ended_at else None,
                "result": result,
                "error": job.exc_info if job.is_failed else None
            }
        except Exception as e:
            return {
                "status": "error",
                "error": f"Failed to fetch job status: {str(e)}"
            }
    
    def cancel_execution(self, execution_id: str) -> Dict[str, Any]:
        """
        Cancel a queued or running execution.
        
        Args:
            execution_id: ID of the execution to cancel
            
        Returns:
            Dictionary with cancellation result
        """
        try:
            job = Job.fetch(execution_id, connection=self.redis_conn)
            
            if job.get_status() in ["queued", "started"]:
                job.cancel()
                job.delete()
                
                # Try to kill the container if it's running
                container_id = f"agent-{execution_id[:10]}"
                try:
                    import subprocess
                    subprocess.run(
                        ["docker", "kill", container_id],
                        check=False,
                        capture_output=True
                    )
                except Exception:
                    pass
                
                return {
                    "execution_id": execution_id,
                    "status": "cancelled"
                }
            else:
                return {
                    "execution_id": execution_id,
                    "status": job.get_status(),
                    "message": "Job already completed or failed, cannot cancel"
                }
        except Exception as e:
            return {
                "status": "error",
                "error": f"Failed to cancel execution: {str(e)}"
            }
