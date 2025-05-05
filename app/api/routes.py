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
from app.utils.security import verify_api_key, validate_agent_code

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
    
    if not file or not file.filename:
        return jsonify({"error": "No file selected"}), 400

    if not file.filename.lower().endswith('.zip'):
        return jsonify({"error": "Only ZIP files are supported"}), 400
    
    # Save file temporarily
    temp_dir = tempfile.mkdtemp()
    temp_file = os.path.join(temp_dir, secure_filename(file.filename))
    
    try:
        file.save(temp_file)
        
        # Get agent storage path
        storage_path = current_app.config.get('AGENT_STORAGE_PATH', '/data/agents')
        
        # Create agent from zip
        agent = Agent.create_from_zip(temp_file, storage_path)
        
        # Validate agent code
        validation = validate_agent_code(os.path.join(storage_path, agent.agent_id))
        
        if not validation["valid"]:
            # If validation fails, delete the agent and return error
            agent.delete()
            return jsonify(validation), 400
        
        # Set author if not specified
        if not agent.author:
            agent.author = key_data.get('user_id', 'unknown')
            agent._save_metadata()
        
        return jsonify(agent.to_dict(include_env_vars=True)), 201
        
    except Exception as e:
        logger.error(f"Error creating agent: {str(e)}")
        return jsonify({"error": f"Failed to create agent: {str(e)}"}), 500
    
    finally:
        # Clean up temp directory
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)

@api.route('/agents/<agent_id>', methods=['PUT'])
def update_agent(agent_id):
    """Update an existing agent."""
    # Check API key
    api_key = request.headers.get('Authorization', '').replace('Bearer ', '')
    valid, key_data = verify_api_key(api_key, 'submit')
    
    if not valid:
        return jsonify({"error": key_data["error"]}), 401
    
    # Get agent storage path
    storage_path = current_app.config.get('AGENT_STORAGE_PATH', '/data/agents')
    
    # Get agent
    agent = Agent.load(agent_id, storage_path)
    
    if not agent:
        return jsonify({"error": f"Agent not found: {agent_id}"}), 404
    
    # Check ownership
    if agent.author != key_data.get('user_id') and 'admin' not in key_data.get('scopes', []):
        return jsonify({"error": "You do not have permission to update this agent"}), 403
    
    # Get update data
    data = request.json
    
    if not data:
        return jsonify({"error": "No update data provided"}), 400
    
    # Update agent
    agent.update(**data)
    
    return jsonify(agent.to_dict(include_env_vars=True))

@api.route('/agents/<agent_id>', methods=['DELETE'])
def delete_agent(agent_id):
    """Delete an agent."""
    # Check API key
    api_key = request.headers.get('Authorization', '').replace('Bearer ', '')
    valid, key_data = verify_api_key(api_key, 'submit')
    
    if not valid:
        return jsonify({"error": key_data["error"]}), 401
    
    # Get agent storage path
    storage_path = current_app.config.get('AGENT_STORAGE_PATH', '/data/agents')
    
    # Get agent
    agent = Agent.load(agent_id, storage_path)
    
    if not agent:
        return jsonify({"error": f"Agent not found: {agent_id}"}), 404
    
    # Check ownership
    if agent.author != key_data.get('user_id') and 'admin' not in key_data.get('scopes', []):
        return jsonify({"error": "You do not have permission to delete this agent"}), 403
    
    # Delete agent
    success = agent.delete()
    
    if success:
        return jsonify({"success": True, "message": f"Agent {agent_id} deleted"}), 200
    else:
        return jsonify({"error": f"Failed to delete agent {agent_id}"}), 500

@api.route('/execute', methods=['POST'])
def execute_agent():
    """Execute an agent with given input."""
    # Check API key
    api_key = request.headers.get('Authorization', '').replace('Bearer ', '')
    valid, key_data = verify_api_key(api_key, 'execute')
    
    if not valid:
        return jsonify({"error": key_data["error"]}), 401
    
    # Get request data
    data = request.json
    
    if not data:
        return jsonify({"error": "No request data provided"}), 400
    
    required_fields = ['agent_id', 'user_id', 'input']
    for field in required_fields:
        if field not in data:
            return jsonify({"error": f"Missing required field: {field}"}), 400
    
    # Generate execution ID
    execution_id = str(uuid.uuid4())
    
    # Set up execution parameters
    execution_params = {
        'execution_id': execution_id,
        'agent_id': data['agent_id'],
        'user_id': data['user_id'],
        'input': data['input'],
        'user_vars': data.get('user_vars', {}),
        'parent_execution_id': data.get('parent_execution_id')
    }
    
    # Get worker and queue execution
    worker = get_worker()
    success = worker.queue_execution(**execution_params)
    
    if not success:
        return jsonify({"error": "Failed to queue execution"}), 500
    
    return jsonify({
        "execution_id": execution_id,
        "agent_id": data['agent_id'],
        "status": "queued"
    })

@api.route('/invoke', methods=['POST'])
def invoke_agent():
    """Invoke an agent from within another agent."""
    # Check API key
    api_key = request.headers.get('Authorization', '').replace('Bearer ', '')
    valid, key_data = verify_api_key(api_key, 'execute')
    
    if not valid:
        return jsonify({"error": key_data["error"]}), 401
    
    # Get request data
    data = request.json
    
    if not data:
        return jsonify({"error": "No request data provided"}), 400
    
    required_fields = ['parent_execution_id', 'agent_id', 'user_id', 'input']
    for field in required_fields:
        if field not in data:
            return jsonify({"error": f"Missing required field: {field}"}), 400
    
    # Get storage path
    storage_path = current_app.config.get('AGENT_STORAGE_PATH', '/data/agents')
    
    # Check if agent exists
    agent = Agent.load(data['agent_id'], storage_path)
    if not agent:
        return jsonify({"error": f"Agent not found: {data['agent_id']}"}), 404
    
    # Generate execution ID
    execution_id = str(uuid.uuid4())
    
    # Set up execution parameters
    execution_params = {
        'execution_id': execution_id,
        'agent_id': data['agent_id'],
        'user_id': data['user_id'],
        'input': data['input'],
        'user_vars': data.get('user_vars', {}),
        'parent_execution_id': data['parent_execution_id']
    }
    
    # Queue execution
    worker = get_worker()
    success = worker.queue_execution(**execution_params)
    
    if not success:
        return jsonify({"error": "Failed to queue execution"}), 500
    
    # For invocations, we want to wait for the result
    # In a real implementation, this might use polling or a callback mechanism
    result = worker.get_execution_result(execution_id, timeout=30)
    
    if not result:
        return jsonify({
            "execution_id": execution_id,
            "agent_id": data['agent_id'],
            "status": "running",
            "message": "Execution is taking longer than expected"
        })
    
    return jsonify(result)

@api.route('/execution/<execution_id>', methods=['GET'])
def get_execution(execution_id):
    """Get the result of an execution."""
    # Check API key
    api_key = request.headers.get('Authorization', '').replace('Bearer ', '')
    valid, key_data = verify_api_key(api_key, 'execute')
    
    if not valid:
        return jsonify({"error": key_data["error"]}), 401
    
    # Get worker
    worker = get_worker()
    
    # Get execution result
    result = worker.get_execution_result(execution_id)
    
    if not result:
        return jsonify({"error": f"Execution not found or still running: {execution_id}"}), 404
    
    return jsonify(result)

@api.route('/messages', methods=['POST'])
def handle_message_callback():
    """Handle message callbacks from agents."""
    # Check API key
    api_key = request.headers.get('Authorization', '').replace('Bearer ', '')
    valid, key_data = verify_api_key(api_key, 'execute')
    
    if not valid:
        return jsonify({"error": key_data["error"]}), 401
    
    # Get request data
    data = request.json
    
    if not data:
        return jsonify({"error": "No message data provided"}), 400
    
    if 'execution_id' not in data or 'message' not in data:
        return jsonify({"error": "Missing required fields: execution_id or message"}), 400
    
    # In a real implementation, this would notify clients of the new message
    # For example, through WebSockets or SSE
    logger.info(f"Message received for execution {data['execution_id']}: {data['message']['content'][:50]}...")
    
    # Store the message in Redis or another persistent store
    worker = get_worker()
    worker.store_message(data['execution_id'], data['message'])
    
    return jsonify({"success": True})

@api.route('/llm', methods=['POST'])
def invoke_llm():
    """Invoke the LLM service."""
    # Check API key
    api_key = request.headers.get('Authorization', '').replace('Bearer ', '')
    valid, key_data = verify_api_key(api_key, 'execute')
    
    if not valid:
        return jsonify({"error": key_data["error"]}), 401
    
    # Get request data
    data = request.json
    
    if not data:
        return jsonify({"error": "No request data provided"}), 400
    
    required_fields = ['execution_id', 'prompt']
    for field in required_fields:
        if field not in data:
            return jsonify({"error": f"Missing required field: {field}"}), 400
    
    # In a real implementation, this would call an actual LLM service
    # For now, return a mock response
    
    prompt = data['prompt']
    model = data.get('model', 'default')
    temperature = data.get('temperature', 0.7)
    max_tokens = data.get('max_tokens', 1000)
    
    # Mock LLM response
    response = {
        "content": f"This is a mock response to: {prompt[:50]}...",
        "model": model,
        "usage": {
            "prompt_tokens": len(prompt.split()),
            "completion_tokens": 20,
            "total_tokens": len(prompt.split()) + 20
        }
    }
    
    # Log LLM call
    logger.info(f"LLM call for execution {data['execution_id']}: {model}, temp={temperature}")
    
    return jsonify(response)

@api.route('/validate', methods=['POST'])
def validate_agent():
    """Validate agent code without submitting."""
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
    extract_dir = os.path.join(temp_dir, 'extracted')
    os.makedirs(extract_dir, exist_ok=True)
    
    try:
        file.save(temp_file)
        
        # Extract zip for validation
        import zipfile
        with zipfile.ZipFile(temp_file, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        
        # Validate the code
        validation_result = validate_agent_code(extract_dir)
        
        return jsonify(validation_result)
        
    except Exception as e:
        logger.error(f"Error validating agent: {str(e)}")
        return jsonify({
            "valid": False,
            "issues": [{
                "type": "validation_error",
                "message": f"Failed to validate agent: {str(e)}"
            }],
            "reason": f"Validation error: {str(e)}"
        }), 500
    
    finally:
        # Clean up temp directory
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)

@api.route('/download/<agent_id>', methods=['GET'])
def download_agent(agent_id):
    """Download an agent as a ZIP file."""
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
    
    # Check ownership if agent is not public
    if not agent.is_public and agent.author != key_data.get('user_id') and 'admin' not in key_data.get('scopes', []):
        return jsonify({"error": "You do not have permission to download this agent"}), 403
    
    # Create a temporary ZIP file
    temp_dir = tempfile.mkdtemp()
    zip_file_path = os.path.join(temp_dir, f"{agent_id}.zip")
    
    try:
        # Create ZIP file
        agent_dir = os.path.join(storage_path, agent_id)
        
        import zipfile
        with zipfile.ZipFile(zip_file_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(agent_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    zipf.write(file_path, os.path.relpath(file_path, agent_dir))
        
        # Send the file
        return send_file(
            zip_file_path,
            as_attachment=True,
            download_name=f"{agent.name.replace(' ', '_')}_{agent.version}.zip",
            mimetype='application/zip'
        )
        
    except Exception as e:
        logger.error(f"Error creating agent ZIP: {str(e)}")
        return jsonify({"error": f"Failed to create agent ZIP: {str(e)}"}), 500
    
    finally:
        # Cleanup will be handled by Flask after send_file completes
        pass
