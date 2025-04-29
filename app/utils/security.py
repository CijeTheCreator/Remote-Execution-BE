# app/utils/security.py
import os
import re
import ast
import logging
from typing import Dict, Any, List, Tuple, Set

logger = logging.getLogger(__name__)

# List of potentially dangerous modules that should be restricted
RESTRICTED_MODULES = {
    # System access
    "subprocess", "os.system", "os.spawn", "os.popen", "pty",
    # File system unrestricted access
    "shutil", 
    # Network socket direct manipulation
    "socket", 
    # Low-level system interfaces
    "ctypes", "cffi",
    # Code execution/generation
    "exec", "eval", "compile",
    # Serialization that can lead to code execution
    "pickle", "shelve", "marshal",
    # Process manipulation
    "multiprocessing.Process", "threading.Thread",
    # Dynamic module loading
    "importlib", "imp", "__import__"
}

# Restricted operations in AST
RESTRICTED_OPERATIONS = {
    # Built-in functions that can lead to code execution
    "eval", "exec", "compile", "globals", "__import__",
    # Dangerous operations
    "open",  # File operations should be controlled
    "write", "chmod", "chown", "link", "symlink", "unlink",
    # Shell commands
    "system", "spawn", "popen", "run", "call", "check_call", "check_output",
}

# Allowed network modules with restrictions
NETWORK_RESTRICTIONS = {
    "requests": {
        "allowed_methods": ["get", "post", "put", "delete", "head", "options"],
        "blocked_urls": [
            r"^https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|10\.\d+\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[0-1])\.\d+\.\d+|192\.168\.\d+\.\d+)",
            r"^file://",
        ]
    },
    "urllib": {
        "blocked_modules": ["request"],
    }
}

def validate_agent_code(agent_path: str) -> Dict[str, Any]:
    """
    Validate agent code for security concerns.
    
    Args:
        agent_path: Path to the agent code directory
        
    Returns:
        Dict with validation results
    """
    validation_issues = []
    
    # Check each Python file in the directory
    for root, _, files in os.walk(agent_path):
        for file in files:
            if file.endswith(".py"):
                file_path = os.path.join(root, file)
                file_issues = validate_python_file(file_path)
                
                if file_issues:
                    rel_path = os.path.relpath(file_path, agent_path)
                    validation_issues.append({
                        "file": rel_path,
                        "issues": file_issues
                    })
    
    # Check for requirements.txt if present
    req_file = os.path.join(agent_path, "requirements.txt")
    if os.path.exists(req_file):
        req_issues = validate_requirements(req_file)
        if req_issues:
            validation_issues.append({
                "file": "requirements.txt",
                "issues": req_issues
            })
    
    # Overall validation result
    result = {
        "valid": len(validation_issues) == 0,
        "issues": validation_issues if validation_issues else None
    }
    
    if not result["valid"]:
        result["reason"] = "Security concerns detected in agent code"
    
    return result

def validate_python_file(file_path: str) -> List[Dict[str, Any]]:
    """
    Validate a Python file for security concerns.
    
    Args:
        file_path: Path to the Python file to validate
        
    Returns:
        List of security issues found
    """
    issues = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            code = file.read()
        
        # Parse the code
        try:
            tree = ast.parse(code)
            
            # Check for imports
            import_issues = check_imports(tree)
            if import_issues:
                issues.extend(import_issues)
            
            # Check for dangerous operations
            operation_issues = check_operations(tree)
            if operation_issues:
                issues.extend(operation_issues)
                
        except SyntaxError as e:
            issues.append({
                "type": "syntax_error",
                "line": e.lineno,
                "message": f"Syntax error: {str(e)}"
            })
            
    except Exception as e:
        issues.append({
            "type": "file_error",
            "message": f"Error processing file: {str(e)}"
        })
    
    return issues

def check_imports(tree: ast.AST) -> List[Dict[str, Any]]:
    """
    Check for restricted imports in the AST.
    
    Args:
        tree: AST to check
        
    Returns:
        List of import issues
    """
    issues = []
    
    for node in ast.walk(tree):
        # Check for import statements
        if isinstance(node, ast.Import):
            for name in node.names:
                module = name.name
                if module in RESTRICTED_MODULES or any(module.startswith(f"{m}.") for m in RESTRICTED_MODULES):
                    issues.append({
                        "type": "restricted_import",
                        "line": node.lineno,
                        "module": module,
                        "message": f"Restricted module import: {module}"
                    })
        
        # Check for from ... import statements
        elif isinstance(node, ast.ImportFrom):
            module = node.module
            
            if module in RESTRICTED_MODULES or any(module.startswith(f"{m}.") for m in RESTRICTED_MODULES):
                issues.append({
                    "type": "restricted_import",
                    "line": node.lineno,
                    "module": module,
                    "message": f"Restricted module import: {module}"
                })
            
            # Check imported names
            for name in node.names:
                if name.name in RESTRICTED_OPERATIONS:
                    issues.append({
                        "type": "restricted_import",
                        "line": node.lineno,
                        "module": f"{module}.{name.name}",
                        "message": f"Restricted function import: {module}.{name.name}"
                    })
    
    return issues

def check_operations(tree: ast.AST) -> List[Dict[str, Any]]:
    """
    Check for restricted operations in the AST.
    
    Args:
        tree: AST to check
        
    Returns:
        List of operation issues
    """
    issues = []
    
    for node in ast.walk(tree):
        # Check for calls to restricted functions
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in RESTRICTED_OPERATIONS:
                issues.append({
                    "type": "restricted_operation",
                    "line": node.lineno,
                    "operation": node.func.id,
                    "message": f"Call to restricted function: {node.func.id}"
                })
            
            # Check for attribute access like os.system
            elif isinstance(node.func, ast.Attribute):
                if node.func.attr in RESTRICTED_OPERATIONS:
                    # Get the full name if possible
                    module_name = ""
                    if isinstance(node.func.value, ast.Name):
                        module_name = node.func.value.id
                    
                    issues.append({
                        "type": "restricted_operation",
                        "line": node.lineno,
                        "operation": f"{module_name}.{node.func.attr}" if module_name else node.func.attr,
                        "message": f"Call to restricted method: {module_name}.{node.func.attr}" if module_name else f"Call to restricted method: {node.func.attr}"
                    })
    
    return issues

def validate_requirements(req_file: str) -> List[Dict[str, Any]]:
    """
    Validate requirements.txt for restricted packages.
    
    Args:
        req_file: Path to requirements.txt
        
    Returns:
        List of requirement issues
    """
    issues = []
    
    # List of packages that shouldn't be installed
    restricted_packages = [
        "cryptography", "pycrypto", "pyOpenSSL",  # Crypto libraries
        "django", "flask", "tornado", "fastapi",  # Web frameworks (should use the hub's)
        "tensorflow", "torch", "pytorch",  # ML libraries (large and potentially expensive)
        "boto3", "google-cloud", "azure",  # Cloud provider SDKs
        "ansible", "fabric", "paramiko",  # Remote execution tools
        "scrapy", "selenium",  # Web scraping/automation
    ]
    
    try:
        with open(req_file, 'r', encoding='utf-8') as f:
            requirements = f.readlines()
        
        for i, line in enumerate(requirements):
            line = line.strip()
            
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue
            
            # Extract package name (remove version specifiers)
            package = re.split(r'[=<>!~]', line)[0].strip().lower()
            
            if package in restricted_packages:
                issues.append({
                    "type": "restricted_package",
                    "line": i + 1,
                    "package": package,
                    "message": f"Restricted package in requirements: {package}"
                })
    
    except Exception as e:
        issues.append({
            "type": "file_error",
            "message": f"Error processing requirements.txt: {str(e)}"
        })
    
    return issues

def verify_api_key(api_key: str, required_scope: str = "execute") -> Tuple[bool, Dict[str, Any]]:
    """
    Verify an API key and check if it has the required scope.
    
    Args:
        api_key: API key to verify
        required_scope: Required scope for the operation
        
    Returns:
        Tuple of (is_valid, metadata)
    """
    # In a real system, this would verify against a database
    # For now, we'll simulate key verification
    
    # This is a placeholder - in a real system, implement proper key verification
    if not api_key:
        return False, {"error": "API key is required"}
    
    if api_key == "test_key":
        return True, {
            "user_id": "test_user",
            "scopes": ["execute", "submit", "admin"],
            "expires_at": "2099-12-31T23:59:59Z"
        }
    
    # Key format: {user_id}:{scope1,scope2}:{expiry_timestamp}:{signature}
    try:
        parts = api_key.split(":")
        if len(parts) != 4:
            return False, {"error": "Invalid API key format"}
        
        user_id, scopes_str, expiry, signature = parts
        scopes = set(scopes_str.split(","))
        
        # Check expiry
        current_time = int(__import__('time').time())
        if int(expiry) < current_time:
            return False, {"error": "API key has expired"}
        
        # Check scope
        if required_scope not in scopes:
            return False, {"error": f"API key lacks required scope: {required_scope}"}
        
        # In a real system, verify the signature
        
        return True, {
            "user_id": user_id,
            "scopes": list(scopes),
            "expires_at": expiry
        }
    
    except Exception:
        return False, {"error": "Invalid API key"}
