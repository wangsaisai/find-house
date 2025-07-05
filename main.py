import os
import google.generativeai as genai
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
import requests

# 加载 .env 文件中的环境变量
load_dotenv()

# 配置 Google Gemini API
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("No GOOGLE_API_KEY found in environment variables.")
genai.configure(api_key=GEMINI_API_KEY)

# 高德地图 MCP 服务器配置
AMAP_MCP_KEY = os.getenv("AMAP_MCP_KEY")
AMAP_MCP_URL = f"https://mcp.amap.com/mcp?key={AMAP_MCP_KEY}"


app = FastAPI(
    title="Commute-Friendly Location Finder",
    description="An API to find a convenient location for two addresses based on public transport.",
    version="1.0.0"
)

class LocationRequest(BaseModel):
    address1: str
    address2: str

def geocode_address(address: str):
    """
    Converts an address to coordinates using Amap Web API.
    """
    url = "https://restapi.amap.com/v3/geocode/geo"
    params = {
        "key": AMAP_MCP_KEY, # Using the same key, assuming it works for web API
        "address": address
    }
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        if data["status"] == "1" and data["geocodes"]:
            location = data["geocodes"][0]["location"]
            return location
        else:
            return None
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Amap API request failed: {e}")


def get_transit_info(origin: str, destination: str):
    """
    Gets transit information between two locations using Amap Web API.
    """
    url = "https://restapi.amap.com/v3/direction/transit/integrated"
    params = {
        "key": AMAP_MCP_KEY,
        "origin": origin,
        "destination": destination,
        "city": "beijing" # Assuming Beijing for now, can be parameterized
    }
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Amap API request failed: {e}")

@app.post("/find_location")
async def find_location(request: LocationRequest):
    """
    Finds a location that is relatively convenient to reach from two addresses via public transport.
    """
    location1 = geocode_address(request.address1)
    location2 = geocode_address(request.address2)

    if not location1 or not location2:
        raise HTTPException(status_code=400, detail="Could not geocode one or both addresses.")

    # Get transit info between the two locations
    transit_info = get_transit_info(location1, location2)

    # Prepare the prompt for Gemini
    prompt = f"""
    我需要为两个人找到一个在北京的便捷会面地点。
    第一个人的地址是: {request.address1}
    第二个人的地址是: {request.address2}

    这是他们之间通过公共交通的路线信息:
    {transit_info}

    请根据这些信息，推荐几个（1-3个）具体的、方便两人碰面的地点（例如商场、地铁站或咖啡馆）。
    对于每个推荐的地点，请用中文详细介绍其周边情况，比如：
    - 日常出行是否便利？
    - 附近有无大型商场或购物中心？
    - 购物和生活是否方便？
    - 为什么这个地点对双方来说都比较方便？
    """

    # Call Gemini LLM
    try:
        model = genai.GenerativeModel('gemini-1.5-pro-latest')
        response = model.generate_content(prompt)
        return {"suggested_location": response.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini API request failed: {e}")

@app.get("/")
def read_root():
    return {"message": "Welcome to the Commute-Friendly Location Finder API"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
