"""
Shared n8n API client configuration.
Used by inject_n8n.py and clear_n8n.py.
"""
import os
import sys
from dotenv import load_dotenv


def get_n8n_config():
    """
    Loads n8n connection configuration from environment variables.
    Returns: (base_url, headers)
    """
    load_dotenv()

    api_key = os.getenv("N8N_API_KEY", "").strip()
    if not api_key:
        print("❌ Error: N8N_API_KEY missing in .env file.")
        sys.exit(1)

    host = os.getenv("N8N_HOST", "localhost").strip()
    port = os.getenv("N8N_PORT", "5678").strip()

    base_url = f"http://{host}:{port}/api/v1"
    headers = {
        "X-N8N-API-KEY": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    return base_url, headers
