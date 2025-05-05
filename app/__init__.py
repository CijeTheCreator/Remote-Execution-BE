# app/__init__.py
"""
Agent Execution Platform

This is the main application package for the agent execution platform,
which allows users to create, manage, and execute software agents.
"""

import os
import logging
from flask import Flask
from flask_cors import CORS

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

__version__ = '0.1.0'

def create_app(config=None):
    """
    Application factory function.
    
    Args:
        config: Configuration dictionary or object
        
    Returns:
        Flask application instance
    """
    app = Flask(__name__)
    
    # Set default configuration
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-key-not-for-production'),
        REDIS_URL=os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
        AGENT_STORAGE_PATH=os.environ.get('AGENT_STORAGE_PATH', '/data/agents'),
        CALLBACK_URL=os.environ.get('CALLBACK_URL', 'http://localhost:5000/api/v1'),
        VERSION=__version__
    )
    
    # Override with provided config
    if config:
        app.config.from_mapping(config)
    
    # Enable CORS
    CORS(app)
    
    # Register API blueprint
    from app.api import api
    app.register_blueprint(api, url_prefix='/api/v1')
    
    # Health check endpoint at root
    @app.route('/')
    def index():
        return {
            "status": "ok",
            "service": "agent-execution-platform",
            "version": __version__
        }
    
    logger.info(f"Application started with version {__version__}")
    
    return app
