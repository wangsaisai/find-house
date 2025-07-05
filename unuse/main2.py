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

    async def get_available_tools(self):
        """获取可用的工具列表"""
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list",
            "params": {}
        }
        
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }
        
        async with self.session.post(self.url, json=payload, headers=headers) as response:
            if response.status != 200:
                text = await response.text()
                logger.error(f"Failed to get tools list: {text}")
                return None
            result = await response.json()
            return result

# 通用工具调用函数
async def call_mcp_tool(tool_name: str, arguments: dict):
    """调用MCP工具的通用方法"""
    async with MCPClient(AMAP_MCP_URL) as client:
        try:
            await client.initialize()
            result = await client.call_tool(tool_name, arguments)
            return result
        except Exception as e:
            logger.error(f"MCP tool call failed for {tool_name}: {e}")
            return None

# 定义可用的工具函数供Gemini调用
async def geocode_address(address: str, city: str = None):
    """地理编码工具 - 将地址转换为坐标"""
    arguments = {"address": address}
    if city:
        arguments["city"] = city
    return await call_mcp_tool("maps_geo", arguments)

async def get_transit_directions(origin: str, destination: str, city: str = None):
    """获取公共交通路线"""
    arguments = {
        "origin": origin,
        "destination": destination
    }
    if city:
        arguments.update({"city": city, "cityd": city})
    return await call_mcp_tool("maps_direction_transit_integrated", arguments)

async def search_around(keywords: str, location: str, radius: str = "3000"):
    """周边搜索"""
    arguments = {
        "keywords": keywords,
        "location": location,
        "radius": radius
    }
    return await call_mcp_tool("maps_around_search", arguments)

async def text_search(keywords: str, city: str = None, citylimit: bool = False):
    """文本搜索"""
    arguments = {"keywords": keywords}
    if city:
        arguments.update({"city": city, "citylimit": citylimit})
    return await call_mcp_tool("maps_text_search", arguments)

def extract_coordinates(geocode_result):
    """从地理编码结果中提取坐标 - 修复版本"""
    if not geocode_result:
        return None
    
    try:
        # 处理多层嵌套的结果结构
        # 结构: {"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": "..."}], "isError": false}}
        
        # 首先检查是否有 result 字段
        if isinstance(geocode_result, dict):
            # 如果有 jsonrpc 字段，说明是完整的响应
            if "result" in geocode_result:
                result_data = geocode_result["result"]
                if "content" in result_data and isinstance(result_data["content"], list):
                    content = result_data["content"]
                    if len(content) > 0 and "text" in content[0]:
                        text_content = content[0]["text"]
                        # 解析JSON字符串
                        parsed_data = json.loads(text_content)
                        if "results" in parsed_data and parsed_data["results"]:
                            location = parsed_data["results"][0].get("location")
                            logger.info(f"Extracted coordinates: {location}")
                            return location
            
            # 如果是直接的内容结构
            elif "content" in geocode_result:
                content = geocode_result["content"]
                if isinstance(content, list) and len(content) > 0:
                    text_content = content[0].get("text")
                    if text_content:
                        parsed_data = json.loads(text_content)
                        if "results" in parsed_data and parsed_data["results"]:
                            location = parsed_data["results"][0].get("location")
                            logger.info(f"Extracted coordinates: {location}")
                            return location
        
        logger.warning(f"Could not extract coordinates from: {geocode_result}")
        return None
        
    except Exception as e:
        logger.error(f"Error extracting coordinates: {e}")
        logger.error(f"Input data structure: {type(geocode_result)}")
        if isinstance(geocode_result, dict):
            logger.error(f"Keys: {list(geocode_result.keys())}")
        return None

def extract_city_from_address(address: str):
    """从地址中提取城市信息"""
    # 常见城市名称
    cities = ['北京', '上海', '广州', '深圳', '杭州', '南京', '武汉', '成都', '重庆', '天津', '西安', '苏州']
    for city in cities:
        if city in address:
            return city
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
        return coord1

class ToolExecutor:
    """工具执行器，帮助Gemini自动选择和调用合适的工具"""
    
    def __init__(self):
        self.tools = {
            "geocode_address": geocode_address,
            "get_transit_directions": get_transit_directions,
            "search_around": search_around,
            "text_search": text_search
        }
    
    async def execute_plan(self, address1: str, address2: str):
        """执行查找计划"""
        results = {}
        
        # 自动检测城市
        city1 = extract_city_from_address(address1)
        city2 = extract_city_from_address(address2)
        target_city = city1 or city2  # 使用检测到的城市
        
        logger.info(f"检测到的城市: {target_city}")
        
        # 步骤1: 对两个地址进行地理编码
        logger.info("执行地理编码...")
        results['location1_result'] = await geocode_address(address1, target_city)
        results['location2_result'] = await geocode_address(address2, target_city)
        
        # 提取坐标
        location1_coords = extract_coordinates(results['location1_result'])
        location2_coords = extract_coordinates(results['location2_result'])
        
        logger.info(f"提取的坐标: location1={location1_coords}, location2={location2_coords}")
        
        if not location1_coords or not location2_coords:
            logger.error("坐标提取失败")
            logger.error(f"原始结果1: {results['location1_result']}")
            logger.error(f"原始结果2: {results['location2_result']}")
            return results, location1_coords, location2_coords, target_city
        
        results['location1_coords'] = location1_coords
        results['location2_coords'] = location2_coords
        
        # 步骤2: 获取公交路线信息
        logger.info("获取公交路线信息...")
        results['transit_info'] = await get_transit_directions(
            location1_coords, location2_coords, target_city
        )
        
        # 步骤3: 计算中点并搜索周边
        midpoint = calculate_midpoint(location1_coords, location2_coords)
        results['midpoint'] = midpoint
        logger.info(f"计算的中点: {midpoint}")
        
        logger.info("搜索中点周边设施...")
        results['nearby_pois'] = await search_around(
            "商场|地铁站|购物中心|咖啡厅", midpoint
        )
        
        # 步骤4: 搜索目标城市的知名地点
        if target_city:
            logger.info(f"搜索{target_city}的知名地点...")
            # 根据不同城市搜索不同的知名地点
            if target_city == "北京":
                keywords = "王府井|西单|三里屯|国贸|中关村"
            elif target_city == "上海":
                keywords = "南京路|淮海路|徐家汇|陆家嘴|静安寺"
            elif target_city == "广州":
                keywords = "天河城|北京路|上下九|珠江新城"
            elif target_city == "深圳":
                keywords = "华强北|万象城|海岸城|福田中心区"
            else:
                keywords = "市中心|购物中心|商业区"
            
            results['central_locations'] = await text_search(keywords, target_city, True)
        
        return results, location1_coords, location2_coords, target_city

@app.post("/find_location")
async def find_location(request: LocationRequest):
    """
    使用 MCP 服务找到一个对两个地址都相对便捷的位置
    """
    logger.info(f"Processing request for addresses: {request.address1}, {request.address2}")
    
    # 使用工具执行器自动执行查找计划
    executor = ToolExecutor()
    results, location1_coords, location2_coords, target_city = await executor.execute_plan(
        request.address1, request.address2
    )
    
    if not location1_coords or not location2_coords:
        return {
            "error": "Could not geocode one or both addresses using MCP service.",
            "debug_info": results,
            "coordinates_debug": {
                "location1_coords": location1_coords,
                "location2_coords": location2_coords,
                "location1_raw": results.get('location1_result'),
                "location2_raw": results.get('location2_result')
            }
        }
    
    # 准备给 Gemini 的提示
    city_info = f"在{target_city}" if target_city else "在检测到的城市"
    
    prompt = f"""
    我需要为两个人找到一个{city_info}的便捷会面地点。

    通过高德地图 MCP 服务自动获取的信息：
    
    第一个人的地址: {request.address1}
    坐标: {location1_coords}
    
    第二个人的地址: {request.address2} 
    坐标: {location2_coords}
    
    检测到的城市: {target_city or "未指定"}
    两地中点坐标: {results.get('midpoint', '未计算')}
    
    公共交通路线信息:
    {json.dumps(results.get('transit_info'), ensure_ascii=False, indent=2) if results.get('transit_info') else "暂无路线信息"}
    
    中点附近的兴趣点:
    {json.dumps(results.get('nearby_pois'), ensure_ascii=False, indent=2) if results.get('nearby_pois') else "暂无周边信息"}
    
    {target_city or "当地"}热门商业区域:
    {json.dumps(results.get('central_locations'), ensure_ascii=False, indent=2) if results.get('central_locations') else "暂无商业区域信息"}

    请根据以上自动收集的信息，推荐 2-3 个具体的、方便两人碰面的地点，并给出到达2个位置的详细路线图。

    请重点考虑：
    1. 地铁线路的便利性和换乘站点
    2. 位于两地之间或交通便利的商业中心
    3. 知名地标和购物中心
    4. 当地的交通特点
    
    推荐地点应包括：
    - 具体地点名称
    - 公共交通信息（地铁/公交）
    - 从两个起点的大致通勤时间
    - 周边设施介绍
    - 选择这个地点的理由
    
    请用中文回答，并且要具体实用。
    """

    try:
        model = genai.GenerativeModel('gemini-1.5-pro-latest')
        response = model.generate_content(prompt)
        
        return {
            "suggested_location": response.text,
            "analysis_data": {
                "detected_city": target_city,
                "source_coordinates": {
                    "address1": f"{request.address1} -> {location1_coords}",
                    "address2": f"{request.address2} -> {location2_coords}",
                    "midpoint": results.get('midpoint')
                },
                "auto_collected_data": {
                    "transit_available": bool(results.get('transit_info')),
                    "nearby_pois_found": bool(results.get('nearby_pois')),
                    "central_locations_found": bool(results.get('central_locations'))
                }
            },
            "raw_mcp_data": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini API request failed: {e}")

# 新增：获取可用工具列表的调试端点
@app.get("/debug/available-tools")
async def debug_available_tools():
    """调试：获取MCP服务器上可用的工具"""
    async with MCPClient(AMAP_MCP_URL) as client:
        await client.initialize()
        tools = await client.get_available_tools()
        return tools

# 保留调试端点
@app.get("/debug/test-geocode/{address}")
async def debug_test_geocode(address: str):
    """调试：测试地理编码功能"""
    city = extract_city_from_address(address)
    result = await geocode_address(address, city)
    coords = extract_coordinates(result)
    return {
        "address": address,
        "detected_city": city,
        "geocode_result": result,
        "extracted_coordinates": coords
    }

@app.get("/debug/test-plan/{address1}/{address2}")
async def debug_test_plan(address1: str, address2: str):
    """调试：测试完整的工具执行计划"""
    executor = ToolExecutor()
    results, coord1, coord2, city = await executor.execute_plan(address1, address2)
    return {
        "detected_city": city,
        "coordinates": {
            "location1": coord1,
            "location2": coord2
        },
        "execution_results": results
    }

@app.get("/")
def read_root():
    return {"message": "Welcome to the MCP-powered Commute-Friendly Location Finder API - Now with Auto Tool Selection!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
