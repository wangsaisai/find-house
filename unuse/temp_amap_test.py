import requests
import os
from dotenv import load_dotenv

load_dotenv()

AMAP_MCP_KEY = os.getenv("AMAP_MCP_KEY")
AMAP_MCP_URL = f"https://mcp.amap.com/mcp?key={AMAP_MCP_KEY}"

try:
    # Initialize the connection as per the curl example
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"
    }
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "test-client",
                "version": "1.0.0"
            }
        }
    }
    response = requests.post(AMAP_MCP_URL, json=payload, headers=headers)
    response.raise_for_status()
    print("Response from initialize method:")
    print(response.json())
except requests.exceptions.RequestException as e:
    print(f"An error occurred: {e}")
