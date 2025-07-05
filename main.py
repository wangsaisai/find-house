import os
import json
import asyncio
import google.generativeai as genai
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
import aiohttp
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    description="An API to find a convenient location for two addresses based on public transport using MCP.",
    version="1.0.0"
)

class LocationRequest(BaseModel):
    address1: str
    address2: str

class MCPClient:
    def __init__(self, url: str):
        self.url = url
        self.session = None
        self.request_id = 0
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    def _next_id(self):
        self.request_id += 1
        return self.request_id
    
    async def initialize(self):
        """初始化 MCP 连接"""
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "clientInfo": {
                    "name": "location-finder",
                    "version": "1.0.0"
                }
            }
        }
        
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }
        
        async with self.session.post(self.url, json=payload, headers=headers) as response:
            if response.status != 200:
                raise HTTPException(status_code=response.status, detail="MCP initialization failed")
            result = await response.json()
            return result
    
    async def call_tool(self, tool_name: str, arguments: dict):
        """调用特定的工具"""
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }
        
        logger.info(f"Calling tool {tool_name} with arguments: {arguments}")
        async with self.session.post(self.url, json=payload, headers=headers) as response:
            if response.status != 200:
                text = await response.text()
                logger.error(f"Failed to call tool {tool_name}: {text}")
                raise HTTPException(status_code=response.status, detail=f"Failed to call tool {tool_name}")
            result = await response.json()
            logger.info(f"Tool {tool_name} result: {result}")
            return result

async def geocode_address_mcp(address: str):
    """使用 MCP 的 maps_geo 工具进行地理编码"""
    async with MCPClient(AMAP_MCP_URL) as client:
        try:
            await client.initialize()
            
            # 使用正确的工具名称 maps_geo
            result = await client.call_tool("maps_geo", {
                "address": address,
                "city": "北京"  # 指定城市提高准确性
            })
            
            # 检查结果格式
            if result and "result" in result:
                return result["result"]
            return result
            
        except Exception as e:
            logger.error(f"MCP geocoding failed for {address}: {e}")
            return None

async def get_transit_info_mcp(origin: str, destination: str):
    """使用 MCP 的 maps_direction_transit_integrated 获取公交路线"""
    async with MCPClient(AMAP_MCP_URL) as client:
        try:
            await client.initialize()
            
            result = await client.call_tool("maps_direction_transit_integrated", {
                "origin": origin,
                "destination": destination,
                "city": "北京",
                "cityd": "北京"
            })
            
            return result
            
        except Exception as e:
            logger.error(f"MCP transit query failed: {e}")
            return None

async def search_poi_around_mcp(location: str, keywords: str = "商场"):
    """使用 MCP 的 maps_around_search 搜索周边兴趣点"""
    async with MCPClient(AMAP_MCP_URL) as client:
        try:
            await client.initialize()
            
            result = await client.call_tool("maps_around_search", {
                "keywords": keywords,
                "location": location,
                "radius": "3000"  # 3公里范围
            })
            
            return result
            
        except Exception as e:
            logger.error(f"MCP POI search failed: {e}")
            return None

async def text_search_mcp(keywords: str):
    """使用 MCP 的 maps_text_search 搜索地点"""
    async with MCPClient(AMAP_MCP_URL) as client:
        try:
            await client.initialize()
            
            result = await client.call_tool("maps_text_search", {
                "keywords": keywords,
                "city": "北京",
                "citylimit": True
            })
            
            return result
            
        except Exception as e:
            logger.error(f"MCP text search failed: {e}")
            return None

def extract_coordinates(geocode_result):
    """从地理编码结果中提取坐标 - 修复版本"""
    if not geocode_result:
        return None
    
    try:
        # 从调试信息可以看到，数据结构是:
        # {"content": [{"type": "text", "text": "{\"results\":[{...\"location\":\"116.326423,39.980618\"...}]}"], "isError": false}
        
        if isinstance(geocode_result, dict) and "content" in geocode_result:
            content = geocode_result["content"]
            if isinstance(content, list) and len(content) > 0:
                text_content = content[0].get("text")
                if text_content:
                    # 解析JSON字符串
                    parsed_data = json.loads(text_content)
                    if "results" in parsed_data and parsed_data["results"]:
                        location = parsed_data["results"][0].get("location")
                        logger.info(f"Extracted coordinates: {location}")
                        return location
        
        logger.warning(f"Could not extract coordinates from: {geocode_result}")
        return None
        
    except Exception as e:
        logger.error(f"Error extracting coordinates: {e}")
        return None

def calculate_midpoint(coord1: str, coord2: str):
    """计算两个坐标的中点"""
    try:
        lon1, lat1 = map(float, coord1.split(','))
        lon2, lat2 = map(float, coord2.split(','))
        mid_lon = (lon1 + lon2) / 2
        mid_lat = (lat1 + lat2) / 2
        return f"{mid_lon},{mid_lat}"
    except Exception as e:
        logger.error(f"Error calculating midpoint: {e}")
        return coord1  # 返回第一个坐标作为备用

@app.post("/find_location")
async def find_location(request: LocationRequest):
    """
    使用 MCP 服务找到一个对两个地址都相对便捷的位置
    """
    logger.info(f"Processing request for addresses: {request.address1}, {request.address2}")
    
    # 使用正确的 MCP 工具进行地理编码
    location1_result = await geocode_address_mcp(request.address1)
    location2_result = await geocode_address_mcp(request.address2)
    
    # 提取坐标
    location1_coords = extract_coordinates(location1_result)
    location2_coords = extract_coordinates(location2_result)
    
    logger.info(f"Geocoding results: location1={location1_coords}, location2={location2_coords}")

    if not location1_coords or not location2_coords:
        return {
            "error": "Could not geocode one or both addresses using MCP service.",
            "debug_info": {
                "location1_result": location1_result,
                "location2_result": location2_result,
                "location1_coords": location1_coords,
                "location2_coords": location2_coords
            }
        }
    
    # 获取公交路线信息
    transit_info = await get_transit_info_mcp(location1_coords, location2_coords)
    
    # 计算中点并搜索周边POI
    midpoint = calculate_midpoint(location1_coords, location2_coords)
    nearby_pois = await search_poi_around_mcp(midpoint, "商场|地铁站|购物中心")
    
    # 搜索一些知名地点作为备选
    central_locations = await text_search_mcp("王府井|西单|三里屯|国贸|中关村")

    # 准备给 Gemini 的提示
    prompt = f"""
    我需要为两个人找到一个在北京的便捷会面地点。

    通过高德地图 MCP 服务获取的信息：
    
    第一个人的地址: {request.address1}
    坐标: {location1_coords}
    
    第二个人的地址: {request.address2} 
    坐标: {location2_coords}
    
    两地中点坐标: {midpoint}
    
    公共交通路线信息:
    {json.dumps(transit_info, ensure_ascii=False, indent=2) if transit_info else "正在获取路线信息..."}
    
    中点附近的兴趣点:
    {json.dumps(nearby_pois, ensure_ascii=False, indent=2) if nearby_pois else "正在搜索附近兴趣点..."}
    
    北京热门商业区域:
    {json.dumps(central_locations, ensure_ascii=False, indent=2) if central_locations else "正在搜索商业区域..."}

    请根据坐标位置和两地中点，推荐 2-3 个具体的、方便两人碰面的地点。

    中关村位置大约在: 116.326423,39.980618
    国贸位置大约在: 116.458850,39.909860
    
    请重点考虑：
    1. 地铁4号线（连接中关村）和地铁1号线、10号线（经过国贸）的换乘站点
    2. 位于两地之间或交通便利的商业中心
    3. 知名地标和购物中心
    
    推荐地点应包括：
    - 具体地点名称
    - 地铁线路和站点信息
    - 从两个起点的大致通勤时间
    - 周边设施介绍
    
    请用中文回答。
    """

    try:
        model = genai.GenerativeModel('gemini-1.5-pro-latest')
        response = model.generate_content(prompt)
        
        return {
            "suggested_location": response.text,
            "source_coordinates": {
                "address1": f"{request.address1} -> {location1_coords}",
                "address2": f"{request.address2} -> {location2_coords}",
                "midpoint": midpoint
            },
            "mcp_data": {
                "transit_info": transit_info,
                "nearby_pois": nearby_pois,
                "central_locations": central_locations
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini API request failed: {e}")

# 保留调试端点
@app.get("/debug/test-geocode/{address}")
async def debug_test_geocode(address: str):
    """调试：测试地理编码功能"""
    result = await geocode_address_mcp(address)
    coords = extract_coordinates(result)
    return {
        "address": address,
        "geocode_result": result,
        "extracted_coordinates": coords
    }

@app.get("/")
def read_root():
    return {"message": "Welcome to the MCP-powered Commute-Friendly Location Finder API"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
