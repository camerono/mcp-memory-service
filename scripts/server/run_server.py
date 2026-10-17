#!/usr/bin/env python3
"""Run the MCP Memory Service with HTTP/HTTPS/mDNS support via FastAPI."""

import os
import sys
import uvicorn
import logging

# Add src to path (handles both root and scripts/server/ locations)
script_dir = os.path.dirname(__file__)
src_path = os.path.join(script_dir, 'src')
if not os.path.exists(src_path):
    # Script is in scripts/server/, go up two levels
    src_path = os.path.join(script_dir, '..', '..', 'src')
sys.path.insert(0, src_path)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Deliberately duplicated from mcp_memory_service.compat._sanitize_log_value:
# this script avoids importing mcp_memory_service before uvicorn.run() (see
# the HTTPS-check comment below), so it can't import the canonical helper.
# KEEP IN SYNC with compat.py and the root run_server.py's copy.
def _sanitize_log_value(value: object) -> str:
    return str(value).replace("\n", "\\n").replace("\r", "\\r").replace("\x1b", "\\x1b")

if __name__ == "__main__":
    # Log configuration
    logger.info("Starting MCP Memory Service FastAPI server with the following configuration:")
    logger.info(f"  Storage Backend: {_sanitize_log_value(os.environ.get('MCP_MEMORY_STORAGE_BACKEND', 'sqlite_vec'))}")
    logger.info(f"  HTTP Port: {_sanitize_log_value(os.environ.get('MCP_HTTP_PORT', '8000'))}")
    logger.info(f"  HTTPS Enabled: {_sanitize_log_value(os.environ.get('MCP_HTTPS_ENABLED', 'false'))}")
    logger.info(f"  HTTPS Port: {_sanitize_log_value(os.environ.get('MCP_HTTPS_PORT', '8443'))}")
    logger.info(f"  mDNS Enabled: {_sanitize_log_value(os.environ.get('MCP_MDNS_ENABLED', 'false'))}")
    logger.info(f"  API Key Set: {'Yes' if os.environ.get('MCP_API_KEY') else 'No'}")
    
    http_port = int(os.environ.get('MCP_HTTP_PORT', 8000))
    
    # Check if HTTPS is enabled. Matches the accepted values of
    # config.base.safe_get_bool_env() without importing it: this script
    # deliberately avoids importing mcp_memory_service before uvicorn.run()
    # so it never triggers config/base.py's module-level load_dotenv() call,
    # keeping this a bare os.environ read -- same "no stray .env" rationale
    # as cli/lifecycle.py's _is_https_enabled().
    # KEEP IN SYNC with the accepted-value tuple in
    # mcp_memory_service.config.base.safe_get_bool_env() (currently
    # true/1/yes/on/enabled) and with check_http_server.py's copy below --
    # this is a deliberate duplication (see rationale above), not a shared
    # constant, so it will not update itself if the canonical set changes.
    if os.environ.get('MCP_HTTPS_ENABLED', 'false').strip().lower() in ('true', '1', 'yes', 'on', 'enabled'):
        https_port = int(os.environ.get('MCP_HTTPS_PORT', 8443))
        
        # Check for environment variable certificates first
        cert_file = os.environ.get('MCP_SSL_CERT_FILE')
        key_file = os.environ.get('MCP_SSL_KEY_FILE')
        
        if cert_file and key_file:
            # Use provided certificates
            if not os.path.exists(cert_file):
                logger.error(f"Certificate file not found: {cert_file}")
                sys.exit(1)
            if not os.path.exists(key_file):
                logger.error(f"Key file not found: {key_file}")
                sys.exit(1)
            logger.info(f"Using provided certificates: {cert_file}")
        else:
            # Generate self-signed certificate if needed
            cert_dir = os.path.expanduser("~/.mcp_memory_certs")
            os.makedirs(cert_dir, exist_ok=True)
            cert_file = os.path.join(cert_dir, "cert.pem")
            key_file = os.path.join(cert_dir, "key.pem")
            
            if not os.path.exists(cert_file) or not os.path.exists(key_file):
                logger.info("Generating self-signed certificate for HTTPS...")
                import subprocess
                subprocess.run([
                    "openssl", "req", "-x509", "-newkey", "rsa:4096",
                    "-keyout", key_file, "-out", cert_file,
                    "-days", "365", "-nodes",
                    "-subj", "/C=US/ST=State/L=City/O=MCP/CN=localhost"
                ], check=True)
                logger.info(f"Certificate generated at {cert_dir}")
        
        # Run with HTTPS
        logger.info(f"Starting HTTPS server on port {https_port}")
        uvicorn.run(
            "mcp_memory_service.web.app:app",
            host="0.0.0.0",
            port=https_port,
            ssl_keyfile=key_file,
            ssl_certfile=cert_file,
            reload=False,
            log_level="info"
        )
    else:
        # Run HTTP only
        logger.info(f"Starting HTTP server on port {http_port}")
        uvicorn.run(
            "mcp_memory_service.web.app:app",
            host="0.0.0.0",
            port=http_port,
            reload=False,
            log_level="info"
        )