# app/api/__init__.py
"""
API module for the agent execution platform.
This module provides the Flask Blueprint for the REST API.
"""

from flask import Blueprint
from app.api.routes import api

__all__ = ['api']

# Version of the API
__version__ = '0.1.0'

def get_blueprint() -> Blueprint:
    """
    Get the API Blueprint.
    
    Returns:
        Blueprint: The Flask Blueprint for the API.
    """
    return api
