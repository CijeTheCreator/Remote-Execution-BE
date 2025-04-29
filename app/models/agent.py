# app/models/agent.py
from typing import Dict, Any, List, Optional
import os
import json
import time
import uuid
import shutil
import zipfile
import tempfile
import logging

logger = logging.getLogger(__name__)

class Agent:
    """
    Model representing an agent in the system.
    
    In a production system, this would likely use a database,
    but for simplicity we're using file storage.
    """
    
    REQUIRED_FIELDS = ["name", "description", "author", "version"]
    METADATA_FILE = "agent.json"
    
    def __init__(
        self,
        agent_id: str,
        name: str,
        description: str,
        author: str,
        version: str,
        storage_path: str = "/data/agents",
        is_public: bool = False,
        created_at: Optional[int] = None,
        updated_at: Optional[int] = None,
        env_vars: Optional[Dict[str, str]] = None,
        tags: Optional[List[str]] = None,
        **kwargs
    ):
        self.agent_id = agent_id
        self.name = name
        self.description = description
        self.author = author
        self.version = version
        self.storage_path = storage_path
        self.is_public = is_public
        self.created_at = created_at or int(time.time())
        self.updated_at = updated_at or self.created_at
        self.env_vars = env_vars or {}
        self.tags = tags or []
        self.metadata = kwargs
    
    @classmethod
    def create_from_zip(cls, zip_file_path: str, storage_path: str) -> 'Agent':
        """
        Create a new agent from a ZIP file.
        
        Args:
            zip_file_path: Path to the ZIP file containing agent code
            storage_path: Base path for storing agents
            
        Returns:
            A new Agent instance
        """
        # Create temporary directory for extraction
        temp_dir = tempfile.mkdtemp(prefix="agent_upload_")
        
        try:
            # Extract ZIP file
            with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
            
            # Check for metadata file
            metadata_path = os.path.join(temp_dir, cls.METADATA_FILE)
            if not os.path.exists(metadata_path):
                raise ValueError(f"Missing required {cls.METADATA_FILE} file")
            
            # Load metadata
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)
            
            # Validate required fields
            for field in cls.REQUIRED_FIELDS:
                if field not in metadata:
                    raise ValueError(f"Missing required field '{field}' in {cls.METADATA_FILE}")
            
            # Generate agent ID (or use provided ID)
            agent_id = metadata.get("agent_id", str(uuid.uuid4()))
            
            # Create agent instance
            agent = cls(
                agent_id=agent_id,
                name=metadata["name"],
                description=metadata["description"],
                author=metadata["author"],
                version=metadata["version"],
                storage_path=storage_path,
                env_vars=metadata.get("env_vars", {}),
                tags=metadata.get("tags", []),
                is_public=metadata.get("is_public", False),
                **{k: v for k, v in metadata.items() if k not in cls.REQUIRED_FIELDS + ["agent_id", "env_vars", "tags", "is_public"]}
            )
            
            # Create agent directory
            agent_dir = os.path.join(storage_path, agent_id)
            os.makedirs(agent_dir, exist_ok=True)
            
            # Copy files
            for item in os.listdir(temp_dir):
                source = os.path.join(temp_dir, item)
                destination = os.path.join(agent_dir, item)
                
                if os.path.isdir(source):
                    shutil.copytree(source, destination, dirs_exist_ok=True)
                else:
                    shutil.copy2(source, destination)
            
            # Save metadata
            agent._save_metadata()
            
            return agent
            
        finally:
            # Clean up temp directory
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    @classmethod
    def load(cls, agent_id: str, storage_path: str) -> Optional['Agent']:
        """
        Load an agent from storage.
        
        Args:
            agent_id: ID of the agent to load
            storage_path: Base path for agent storage
            
        Returns:
            Agent instance or None if not found
        """
        agent_dir = os.path.join(storage_path, agent_id)
        metadata_path = os.path.join(agent_dir, cls.METADATA_FILE)
        
        if not os.path.exists(metadata_path):
            return None
        
        try:
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)
            
            # Create agent instance
            return cls(
                agent_id=agent_id,
                storage_path=storage_path,
                **metadata
            )
        except Exception as e:
            logger.error(f"Failed to load agent {agent_id}: {str(e)}")
            return None
    
    @classmethod
    def list_agents(cls, storage_path: str, public_only: bool = False) -> List['Agent']:
        """
        List all available agents.
        
        Args:
            storage_path: Base path for agent storage
            public_only: If True, only return public agents
            
        Returns:
            List of Agent instances
        """
        agents = []
        
        if not os.path.exists(storage_path):
            return agents
        
        for agent_id in os.listdir(storage_path):
            agent = cls.load(agent_id, storage_path)
            if agent and (not public_only or agent.is_public):
                agents.append(agent)
        
        return agents
    
    def _save_metadata(self) -> None:
        """Save agent metadata to disk."""
        agent_dir = os.path.join(self.storage_path, self.agent_id)
        os.makedirs(agent_dir, exist_ok=True)
        
        metadata_path = os.path.join(agent_dir, self.METADATA_FILE)
        
        metadata = {
            "name": self.name,
            "description": self.description,
            "author": self.author,
            "version": self.version,
            "is_public": self.is_public,
            "created_at": self.created_at,
            "updated_at": int(time.time()),
            "env_vars": self.env_vars,
            "tags": self.tags,
            **self.metadata
        }
        
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        self.updated_at = metadata["updated_at"]
    
    def update(self, **kwargs) -> None:
        """
        Update agent properties.
        
        Args:
            **kwargs: Properties to update
        """
        # Update supported fields
        for field in ["name", "description", "version", "is_public", "env_vars", "tags"]:
            if field in kwargs:
                setattr(self, field, kwargs[field])
        
        # Update metadata
        for key, value in kwargs.items():
            if key not in ["agent_id", "storage_path", "created_at", "updated_at"]:
                self.metadata[key] = value
        
        # Save to disk
        self._save_metadata()
    
    def delete(self) -> bool:
        """
        Delete the agent.
        
        Returns:
            True if deletion was successful
        """
        agent_dir = os.path.join(self.storage_path, self.agent_id)
        
        try:
            shutil.rmtree(agent_dir)
            return True
        except Exception as e:
            logger.error(f"Failed to delete agent {self.agent_id}: {str(e)}")
            return False
    
    def to_dict(self, include_env_vars: bool = False) -> Dict[str, Any]:
        """
        Convert agent to dictionary representation.
        
        Args:
            include_env_vars: Whether to include environment variables
            
        Returns:
            Dictionary representation of the agent
        """
        agent_dict = {
            "agent_id": self.agent_id,
            "name": self.name,
            "description": self.description,
            "author": self.author,
            "version": self.version,
            "is_public": self.is_public,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "tags": self.tags,
        }
        
        if include_env_vars:
            agent_dict["env_vars"] = self.env_vars
        
        # Add metadata
        for key, value in self.metadata.items():
            if key not in agent_dict:
                agent_dict[key] = value
        
        return agent_dict
