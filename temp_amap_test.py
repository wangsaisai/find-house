import requests
import os
from dotenv import load_dotenv

load_dotenv()

AMAP_MCP_KEY = os.getenv("AMAP_MCP_KEY")
AMAP_MCP_URL = f"https://mcp.amap.com/mcp?key={AMAP_MCP_KEY}"

try:
    # Let's try to call a hypothetical 'geocode' tool.
    payload = {
        "tool": "geocode",
        "arguments": {
            "address": "北京市朝阳区阜通东大街6号"
        }
    }
    response = requests.post(AMAP_MCP_URL, json=payload)
    response.raise_for_status()
    print("Response from geocode tool:")
    print(response.json())
except requests.exceptions.RequestException as e:
    print(f"An error occurred: {e}")
