# app/executor/context.py
from typing import List, Dict, Any, Optional, Callable
import json
import uuid
import logging

logger = logging.getLogger(__name__)

class Message:
    """Representation of a chat message in the agent's context."""
    
    def __init__(self, role: str, content: str, message_id: Optional[str] = None):
        self.role = role  # 'user', 'agent', 'system'
        self.content = content
        self.message_id = message_id or str(uuid.uuid4())
        self.timestamp = int(__import__('time').time())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "message_id": self.message_id,
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Message':
        msg = cls(data["role"], data["content"], data.get("message_id"))
        msg.timestamp = data.get("timestamp", msg.timestamp)
        return msg


class AgentContext:
    """
    Execution context provided to each agent's run() function.
    Serves as the interface between the agent code and the Hub system.
    """
    
    def __init__(
        self,
        execution_id: str,
        agent_id: str,
        user_id: str,
        chat_history: List[Dict[str, Any]],
        environment_vars: Dict[str, str],
        user_vars: Dict[str, Any],
        callback_url: str,
        api_key: str,
    ):
        self.execution_id = execution_id
        self.agent_id = agent_id
        self.user_id = user_id
        self.messages = [Message.from_dict(msg) for msg in chat_history]
        self.env_vars = environment_vars
        self.user_vars = user_vars
        self._callback_url = callback_url
        self._api_key = api_key
        self._execution_results = []
        self._llm_calls = 0
        self._start_time = int(__import__('time').time())
    
    def send_message(self, content: str, role: str = "agent") -> None:
        """
        Send a message to the user.
        
        Args:
            content: The message content
            role: The sender role (default: 'agent')
        """
        message = Message(role, content)
        self._execution_results.append({
            "type": "message",
            "content": message.to_dict()
        })
        
        # Send message back to hub system in real-time
        try:
            import requests
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}"
            }
            payload = {
                "execution_id": self.execution_id,
                "message": message.to_dict()
            }
            requests.post(f"{self._callback_url}/messages", 
                          json=payload, headers=headers, timeout=5)
        except Exception as e:
            logger.error(f"Failed to send message callback: {str(e)}")
    
    def invoke_agent(self, agent_id: str, input_message: str) -> Dict[str, Any]:
        """
        Invoke another agent from within this agent.
        
        Args:
            agent_id: ID of the agent to invoke
            input_message: Message to send to the invoked agent
            
        Returns:
            Response from the invoked agent
        """
        try:
            import requests
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}"
            }
            payload = {
                "parent_execution_id": self.execution_id,
                "agent_id": agent_id,
                "user_id": self.user_id,
                "input": input_message
            }
            response = requests.post(
                f"{self._callback_url}/invoke",
                json=payload,
                headers=headers,
                timeout=30
            )
            result = response.json()
            
            # Log the invocation
            self._execution_results.append({
                "type": "agent_invocation",
                "agent_id": agent_id,
                "input": input_message,
                "result": result
            })
            
            return result
        except Exception as e:
            error_msg = f"Failed to invoke agent {agent_id}: {str(e)}"
            logger.error(error_msg)
            return {"error": error_msg}
    
    def invoke_llm(
        self, 
        prompt: str, 
        model: str = "default", 
        temperature: float = 0.7,
        max_tokens: int = 1000,
        system_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Invoke the Hub's LLM service.
        
        Args:
            prompt: The prompt to send to the LLM
            model: Model identifier (default="default")
            temperature: Sampling temperature (default=0.7)
            max_tokens: Maximum tokens in response (default=1000)
            system_prompt: Optional system prompt
            
        Returns:
            LLM response
        """
        try:
            import requests
            self._llm_calls += 1
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}"
            }
            
            payload = {
                "execution_id": self.execution_id,
                "prompt": prompt,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens
            }
            
            if system_prompt:
                payload["system_prompt"] = system_prompt
                
            response = requests.post(
                f"{self._callback_url}/llm",
                json=payload,
                headers=headers,
                timeout=30
            )
            
            result = response.json()
            
            # Log the LLM call
            self._execution_results.append({
                "type": "llm_call",
                "prompt": prompt,
                "model": model,
                "result": result
            })
            
            return result
        except Exception as e:
            error_msg = f"Failed to invoke LLM: {str(e)}"
            logger.error(error_msg)
            return {"error": error_msg}
    
    def get_execution_results(self) -> Dict[str, Any]:
        """Get complete execution results and metadata."""
        end_time = int(__import__('time').time())
        return {
            "execution_id": self.execution_id,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "results": self._execution_results,
            "stats": {
                "llm_calls": self._llm_calls,
                "duration_seconds": end_time - self._start_time,
                "message_count": len([r for r in self._execution_results if r["type"] == "message"])
            }
        }
    
    @property
    def latest_user_message(self) -> Optional[Message]:
        """Get the most recent user message."""
        for msg in reversed(self.messages):
            if msg.role == "user":
                return msg
        return None
