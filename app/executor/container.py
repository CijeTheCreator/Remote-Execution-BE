# app/executor/container.py
import os
import json
import uuid
import tempfile
import shutil
import logging
import subprocess
from typing import Dict, Any
import importlib.util
import sys

from app.executor.context import AgentContext, Message

logger = logging.getLogger(__name__)

class ContainerExecutor:
    """
    Handles execution of agent code in a Docker container or directly in process
    depending on configuration and security requirements.
    """
    
    def __init__(
        self,
        container_image: str = "agent-runtime:latest",
        use_containers: bool = True,
        container_timeout: int = 300,
        memory_limit: str = "256m",
        cpu_limit: str = "0.5"
    ):
        self.container_image = container_image
        self.use_containers = use_containers
        self.container_timeout = container_timeout
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
    
    def execute_agent(self, agent_path: str, context_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute an agent with the given context data.
        
        Args:
            agent_path: Path to the agent code directory
            context_data: Dictionary of context data for the agent execution
            
        Returns:
            Execution results
        """
        execution_id = context_data["execution_id"]
        agent_id = context_data["agent_id"]

        logger.info(f"Executing agent {agent_id} with execution ID {execution_id}")
        
        if not os.path.exists(os.path.join(agent_path, "agent.py")):
            return {
                "status": "error",
                "error": f"Agent entry point not found: {agent_path}/agent.py",
                "execution_id": execution_id,
                "agent_id": agent_id
            }
        
        messages = [Message.from_dict(msg) for msg in context_data.get("messages", [])]
        
        context = AgentContext(
            execution_id=execution_id,
            agent_id=agent_id,
            user_id=context_data["user_id"],
            chat_history=context_data.get("messages", []),
            environment_vars=context_data.get("env_vars", {}),
            user_vars=context_data.get("user_vars", {}),
            callback_url=context_data.get("callback_url", ""),
            api_key=context_data.get("api_key", "")
        )
        
        if self.use_containers:
            return self._execute_in_container(agent_path, context)
        else:
            return self._execute_in_process(agent_path, context)
    
    def _execute_in_container(self, agent_path: str, context: AgentContext) -> Dict[str, Any]:
        execution_id = context.execution_id
        agent_id = context.agent_id
        
        temp_dir = tempfile.mkdtemp(prefix=f"agent-{execution_id[:8]}-")
        
        try:
            agent_temp_path = os.path.join(temp_dir, "agent")
            shutil.copytree(agent_path, agent_temp_path)
            
            context_file = os.path.join(temp_dir, "context.json")
            with open(context_file, "w") as f:
                context_data = {
                    "execution_id": context.execution_id,
                    "agent_id": context.agent_id,
                    "user_id": context.user_id,
                    "messages": [msg.to_dict() for msg in context.messages],
                    "env_vars": context.env_vars,
                    "user_vars": context.user_vars,
                    "callback_url": context._callback_url,
                    "api_key": context._api_key
                }
                json.dump(context_data, f)
            
            output_file = os.path.join(temp_dir, "output.json")
            container_name = f"agent-{execution_id[:10]}"
            
            cmd = [
                "docker", "run",
                "--name", container_name,
                "--rm",
                "-v", f"{temp_dir}:/workspace",
                "--memory", self.memory_limit,
                "--cpus", self.cpu_limit,
                "--network", "host",
                self.container_image,
                "python", "-c", 
                "import sys; "
                "sys.path.append('/workspace/agent'); "
                "from agent import Agent; "
                "import json; "
                "from app.executor.context import AgentContext, Message; "
                "with open('/workspace/context.json', 'r') as f: "
                "    context_data = json.load(f); "
                "context = AgentContext("
                "    execution_id=context_data['execution_id'], "
                "    agent_id=context_data['agent_id'], "
                "    user_id=context_data['user_id'], "
                "    chat_history=context_data['messages'], "
                "    environment_vars=context_data['env_vars'], "
                "    user_vars=context_data['user_vars'], "
                "    callback_url=context_data['callback_url'], "
                "    api_key=context_data['api_key']"
                "); "
                "agent = Agent(); "
                "agent.run(context); "
                "with open('/workspace/output.json', 'w') as f: "
                "    json.dump(context.get_execution_results(), f)"
            ]
            
            logger.info(f"Running container for execution {execution_id}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.container_timeout
            )
            
            if os.path.exists(output_file):
                with open(output_file, "r") as f:
                    return json.load(f)
            else:
                error_msg = result.stderr or "Container execution failed with no output"
                logger.error(f"Container execution failed: {error_msg}")
                return {
                    "status": "error",
                    "error": error_msg,
                    "execution_id": execution_id,
                    "agent_id": agent_id,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "exit_code": result.returncode
                }
        
        except subprocess.TimeoutExpired:
            logger.error(f"Container execution timed out after {self.container_timeout} seconds")
            return {
                "status": "error",
                "error": f"Execution timed out after {self.container_timeout} seconds",
                "execution_id": execution_id,
                "agent_id": agent_id
            }
        
        except Exception as e:
            logger.error(f"Error executing agent in container: {str(e)}")
            return {
                "status": "error",
                "error": f"Container execution error: {str(e)}",
                "execution_id": execution_id,
                "agent_id": agent_id
            }
        
        finally:
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                logger.warning(f"Failed to clean up temp directory: {str(e)}")
    
    def _execute_in_process(self, agent_path: str, context: AgentContext) -> Dict[str, Any]:
        execution_id = context.execution_id
        agent_id = context.agent_id
        
        try:
            sys.path.append(agent_path)
            
            agent_file = os.path.join(agent_path, "agent.py")
            spec = importlib.util.spec_from_file_location("agent", agent_file)

            if spec is None or spec.loader is None:
                raise ImportError(f"Could not load spec for agent module from {agent_file}")
            
            agent_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(agent_module)
            
            agent = agent_module.Agent()
            agent.run(context)
            
            return context.get_execution_results()
        
        except Exception as e:
            logger.error(f"Error executing agent in process: {str(e)}")
            return {
                "status": "error",
                "error": f"Execution error: {str(e)}",
                "execution_id": execution_id,
                "agent_id": agent_id
            }
        
        finally:
            if agent_path in sys.path:
                sys.path.remove(agent_path)
