# app/api/schemas.py
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field, validator
from datetime import datetime


class HealthCheckResponse(BaseModel):
    """Health check response schema."""
    status: str
    timestamp: str
    version: str


class ApiKey(BaseModel):
    """API key validation schema."""
    api_key: str = Field(..., description="API key for authentication")


class MessageSchema(BaseModel):
    """Schema for chat messages."""
    role: str = Field(..., description="Role of the message sender (user, agent, system)")
    content: str = Field(..., description="Content of the message")
    message_id: Optional[str] = Field(None, description="Unique ID for the message")
    timestamp: Optional[int] = Field(None, description="Timestamp of the message")


class AgentListQueryParams(BaseModel):
    """Query parameters for listing agents."""
    public_only: bool = Field(False, description="If true, only return public agents")


class AgentMetadata(BaseModel):
    """Base schema for agent metadata."""
    name: str = Field(..., description="Name of the agent")
    description: str = Field(..., description="Description of the agent")
    author: str = Field(..., description="Author/creator of the agent")
    version: str = Field(..., description="Version of the agent")
    is_public: bool = Field(False, description="Whether the agent is publicly accessible")
    tags: List[str] = Field(default_factory=list, description="Tags associated with the agent")


class AgentCreateRequest(AgentMetadata):
    """Schema for agent creation request."""
    env_vars: Dict[str, str] = Field(default_factory=dict, description="Environment variables for the agent")
    agent_id: Optional[str] = Field(None, description="Custom agent ID (optional)")


class AgentResponse(AgentMetadata):
    """Schema for agent API response."""
    agent_id: str = Field(..., description="Unique ID of the agent")
    created_at: int = Field(..., description="Creation timestamp")
    updated_at: int = Field(..., description="Last update timestamp")
    env_vars: Optional[Dict[str, str]] = Field(None, description="Environment variables (only shown to owner/admin)")


class AgentListResponse(BaseModel):
    """Schema for listing agents response."""
    agents: List[AgentResponse] = Field(..., description="List of agents")
    count: int = Field(..., description="Total number of agents returned")


class AgentUpdateRequest(BaseModel):
    """Schema for updating an agent."""
    name: Optional[str] = Field(None, description="Name of the agent")
    description: Optional[str] = Field(None, description="Description of the agent")
    version: Optional[str] = Field(None, description="Version of the agent")
    is_public: Optional[bool] = Field(None, description="Whether the agent is publicly accessible")
    env_vars: Optional[Dict[str, str]] = Field(None, description="Environment variables for the agent")
    tags: Optional[List[str]] = Field(None, description="Tags associated with the agent")


class ExecutionRequest(BaseModel):
    """Schema for agent execution request."""
    agent_id: str = Field(..., description="ID of the agent to execute")
    user_id: str = Field(..., description="ID of the user making the request")
    input: str = Field(..., description="Input message for the agent")
    parent_execution_id: Optional[str] = Field(None, description="ID of a parent execution (for agent invocations)")
    user_vars: Optional[Dict[str, Any]] = Field(None, description="User-provided variables for execution context")


class LLMRequest(BaseModel):
    """Schema for LLM API request."""
    execution_id: str = Field(..., description="ID of the associated execution")
    prompt: str = Field(..., description="Prompt to send to the LLM")
    model: str = Field("default", description="Model identifier")
    temperature: float = Field(0.7, description="Sampling temperature")
    max_tokens: int = Field(1000, description="Maximum tokens in response")
    system_prompt: Optional[str] = Field(None, description="Optional system prompt")


class LLMResponse(BaseModel):
    """Schema for LLM API response."""
    content: str = Field(..., description="Generated text content")
    model: str = Field(..., description="Model used for generation")
    usage: Dict[str, int] = Field(..., description="Token usage statistics")


class MessageCallback(BaseModel):
    """Schema for message callback."""
    execution_id: str = Field(..., description="ID of the associated execution")
    message: MessageSchema = Field(..., description="Message sent by the agent")


class ValidationError(BaseModel):
    """Schema for validation errors."""
    detail: List[Dict[str, Any]] = Field(..., description="Validation error details")


class ValidationResult(BaseModel):
    """Schema for agent code validation result."""
    valid: bool = Field(..., description="Whether the agent code is valid")
    issues: Optional[List[Dict[str, Any]]] = Field(None, description="List of validation issues")
    reason: Optional[str] = Field(None, description="Reason for validation failure")


class ExecutionResult(BaseModel):
    """Schema for execution result."""
    execution_id: str = Field(..., description="ID of the execution")
    agent_id: str = Field(..., description="ID of the executed agent")
    user_id: str = Field(..., description="ID of the user")
    results: List[Dict[str, Any]] = Field(..., description="Execution results")
    stats: Dict[str, Any] = Field(..., description="Execution statistics")


class Error(BaseModel):
    """Schema for error responses."""
    error: str = Field(..., description="Error message")
