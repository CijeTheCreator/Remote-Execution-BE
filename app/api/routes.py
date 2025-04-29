# app/api/routes.py
from flask import Blueprint, request, jsonify, current_app, send_file
import os
import uuid
import logging
from datetime import datetime
from werkzeug.utils import secure_filename
import tempfile

from app.models.agent import Agent
from app.executor.worker import AgentExecutorWorker
from app.utils.security import verify_api_key

# Set up logging
logger = logging.getLogger(__name__)

# Create blueprint
api = Blueprint('api', __name__)

# Helper function to get agent worker
def get_worker():
    redis_url = current_app.config.get('REDIS_URL', 'redis://localhost:6379/0')
    agent_storage = current_app.config.get('AGENT_STORAGE_PATH', '/data/agents')
    callback_url = current_app.config.get('CALLBACK_URL', 'http://localhost:5000/api/v1')
    
    return AgentExecutorWorker(
        redis_url=redis_url,
        agent_storage_path=agent_storage,
        callback_url=callback_url
    )

@api.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "version": current_app.config.get('VERSION', '0.1.0')
    })

@api.route('/agents', methods=['GET'])
def list_agents():
    """List all available agents."""
    # Check API key
    api_key = request.headers.get('Authorization', '').replace('Bearer ', '')
    valid, key_data = verify_api_key(api_key, 'read')
    
    if not valid:
        return jsonify({"error": key_data["error"]}), 401
    
    # Get parameters
    public_only = request.args.get('public_only', 'false').lower() == 'true'
    
    # Get agent storage path
    storage_path = current_app.config.get('AGENT_STORAGE_PATH', '/data/agents')
    
    # List agents
    agents = Agent.list_agents(storage_path, public_only=public_only)
    
    # Convert to dict for response
    result = [agent.to_dict() for agent in agents]
    
    return jsonify({
        "agents": result,
        "count": len(result)
    })

@api.route('/agents/<agent_id>', methods=['GET'])
def get_agent(agent_id):
    """Get details for a specific agent."""
    # Check API key
    api_key = request.headers.get('Authorization', '').replace('Bearer ', '')
    valid, key_data = verify_api_key(api_key, 'read')
    
    if not valid:
        return jsonify({"error": key_data["error"]}), 401
    
    # Get agent storage path
    storage_path = current_app.config.get('AGENT_STORAGE_PATH', '/data/agents')
    
    # Get agent
    agent = Agent.load(agent_id, storage_path)
    
    if not agent:
        return jsonify({"error": f"Agent not found: {agent_id}"}), 404
    
    # Include env vars if admin or owner
    include_env_vars = 'admin' in key_data.get('scopes', []) or agent.author == key_data.get('user_id')
    
    return jsonify(agent.to_dict(include_env_vars=include_env_vars))

@api.route('/agents', methods=['POST'])
def submit_agent():
    """Submit a new agent."""
    # Check API key
    api_key = request.headers.get('Authorization', '').replace('Bearer ', '')
    valid, key_data = verify_api_key(api_key, 'submit')
    
    if not valid:
        return jsonify({"error": key_data["error"]}), 401
    
    # Check for file
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    if not file.filename.endswith('.zip'):
        return jsonify({"error": "Only ZIP files are supported"}), 400
    
    # Save file temporarily
    temp_dir = tempfile.mkdtemp()
    temp_file = os.path.join(temp_dir, secure_filename(file.filename))
    
    try:
        file.save(temp_file)
        
        # Get agent storage path
