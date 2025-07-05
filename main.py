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

# 定义可用的工具函数
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

async def get_walking_directions(origin: str, destination: str):
    """获取步行路线"""
    arguments = {
        "origin": origin,
        "destination": destination
    }
    return await call_mcp_tool("maps_direction_walking", arguments)

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

def extract_coordinates_and_city(geocode_result):
    """从地理编码结果中提取坐标和城市信息"""
    if not geocode_result:
        return None, None
    
    try:
        if isinstance(geocode_result, dict):
            if "result" in geocode_result:
                result_data = geocode_result["result"]
                if "content" in result_data and isinstance(result_data["content"], list):
                    content = result_data["content"]
                    if len(content) > 0 and "text" in content[0]:
                        text_content = content[0]["text"]
                        parsed_data = json.loads(text_content)
                        if "results" in parsed_data and parsed_data["results"]:
                            first_result = parsed_data["results"][0]
                            location = first_result.get("location")
                            city = first_result.get("city", "").replace("市", "")
                            province = first_result.get("province", "").replace("市", "")
                            
                            detected_city = city if city else province
                            
                            logger.info(f"Extracted coordinates: {location}, city: {detected_city}")
                            return location, detected_city
            
            elif "content" in geocode_result:
                content = geocode_result["content"]
                if isinstance(content, list) and len(content) > 0:
                    text_content = content[0].get("text")
                    if text_content:
                        parsed_data = json.loads(text_content)
                        if "results" in parsed_data and parsed_data["results"]:
                            first_result = parsed_data["results"][0]
                            location = first_result.get("location")
                            city = first_result.get("city", "").replace("市", "")
                            province = first_result.get("province", "").replace("市", "")
                            
                            detected_city = city if city else province
                            
                            logger.info(f"Extracted coordinates: {location}, city: {detected_city}")
                            return location, detected_city
        
        logger.warning(f"Could not extract coordinates from: {geocode_result}")
        return None, None
        
    except Exception as e:
        logger.error(f"Error extracting coordinates: {e}")
        return None, None

def extract_city_from_address(address: str):
    """从地址中提取城市信息"""
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
            "get_walking_directions": get_walking_directions,
            "search_around": search_around,
            "text_search": text_search
        }
    
    async def execute_plan(self, address1: str, address2: str):
        """执行查找计划"""
        results = {}
        
        # 步骤1: 对两个地址进行地理编码并自动检测城市
        logger.info("执行地理编码...")
        results['location1_result'] = await geocode_address(address1)
        results['location2_result'] = await geocode_address(address2)
        
        # 提取坐标和城市信息
        location1_coords, city1 = extract_coordinates_and_city(results['location1_result'])
        location2_coords, city2 = extract_coordinates_and_city(results['location2_result'])
        
        # 确定目标城市
        target_city = city1 or city2 or extract_city_from_address(address1) or extract_city_from_address(address2)
        
        logger.info(f"检测到的城市: city1={city1}, city2={city2}, target={target_city}")
        logger.info(f"提取的坐标: location1={location1_coords}, location2={location2_coords}")
        
        if not location1_coords or not location2_coords:
            logger.error("坐标提取失败")
            return results, location1_coords, location2_coords, target_city
        
        results['location1_coords'] = location1_coords
        results['location2_coords'] = location2_coords
        results['detected_city'] = target_city
        
        # 步骤2: 获取公交路线信息
        logger.info("获取公交路线信息...")
        transit_attempts = [
            {"origin": location1_coords, "destination": location2_coords},
            {"origin": location1_coords, "destination": location2_coords, "city": target_city, "cityd": target_city} if target_city else None,
            {"origin": address1, "destination": address2},
            {"origin": address1, "destination": address2, "city": target_city, "cityd": target_city} if target_city else None
        ]
        
        transit_info = None
        for i, params in enumerate(transit_attempts):
            if params is None:
                continue
            try:
                logger.info(f"尝试公交路线查询方案 {i+1}: {params}")
                transit_info = await call_mcp_tool("maps_direction_transit_integrated", params)
                
                if transit_info and isinstance(transit_info, dict):
                    result_content = transit_info.get("result", {})
                    if not result_content.get("isError", True):
                        logger.info(f"公交路线查询成功，使用方案 {i+1}")
                        break
                    else:
                        logger.warning(f"方案 {i+1} 失败: {result_content}")
                        
            except Exception as e:
                logger.warning(f"公交路线查询方案 {i+1} 异常: {e}")
                continue
        
        results['transit_info'] = transit_info
        
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
            if target_city == "北京":
                keywords = "王府井|西单|三里屯|国贸|中关村"
            elif target_city == "上海":
                keywords = "南京路|淮海路|徐家汇|陆家嘴|静安寺|人民广场|外滩"
            elif target_city == "广州":
                keywords = "天河城|北京路|上下九|珠江新城"
            elif target_city == "深圳":
                keywords = "华强北|万象城|海岸城|福田中心区"
            else:
                keywords = "市中心|购物中心|商业区"
            
            results['central_locations'] = await text_search(keywords, target_city, True)
        
        # 步骤5: 获取到推荐地点的详细路线（如果有中点周边信息）
        walking_routes = {}
        if results.get('nearby_pois'):
            try:
                poi_content = results['nearby_pois'].get('result', {}).get('content', [])
                if poi_content and len(poi_content) > 0:
                    poi_text = poi_content[0].get('text', '')
                    if poi_text:
                        poi_data = json.loads(poi_text)
                        pois = poi_data.get('pois', [])
                        
                        # 获取前3个重要POI的步行路线
                        important_pois = []
                        for poi in pois[:5]:  # 取前5个POI
                            if any(keyword in poi.get('name', '') for keyword in ['地铁站', '商场', '购物中心']):
                                important_pois.append(poi)
                        
                        for poi in important_pois[:3]:  # 最多3个
                            poi_name = poi.get('name', '')
                            # 尝试获取从两个起点到POI的步行路线
                            try:
                                route1 = await get_walking_directions(location1_coords, midpoint)
                                route2 = await get_walking_directions(location2_coords, midpoint)
                                walking_routes[poi_name] = {
                                    'from_location1': route1,
                                    'from_location2': route2
                                }
                            except Exception as e:
                                logger.warning(f"获取到{poi_name}的步行路线失败: {e}")
            except Exception as e:
                logger.warning(f"解析POI数据失败: {e}")
        
        results['walking_routes'] = walking_routes
        
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
                "target_city": target_city
            }
        }
    
    # 检查公交信息是否可用
    transit_available = False
    transit_error = "暂无路线信息"
    if results.get('transit_info'):
        transit_result = results['transit_info'].get('result', {})
        if not transit_result.get('isError', True):
            transit_available = True
        else:
            content = transit_result.get('content', [])
            if content and len(content) > 0:
                transit_error = content[0].get('text', '公交路线查询失败')
    
    # 准备给 Gemini 的详细提示
    city_info = f"在{target_city}" if target_city else "在检测到的城市"
    
    prompt = f"""
    我需要为两个人找到一个{city_info}的便捷会面地点，并提供详细的出行路线指南。

    **地址信息：**
    - 地点A: {request.address1} (坐标: {location1_coords})
    - 地点B: {request.address2} (坐标: {location2_coords})
    - 检测城市: {target_city}
    - 中点坐标: {results.get('midpoint', '未计算')}

    **通过高德地图API获取的数据：**

    公共交通信息:
    {"✅ 路线查询成功" if transit_available else f"❌ 路线查询失败: {transit_error}"}
    {json.dumps(results.get('transit_info'), ensure_ascii=False, indent=2) if transit_available else ""}

    中点附近的设施:
    {json.dumps(results.get('nearby_pois'), ensure_ascii=False, indent=2) if results.get('nearby_pois') else "暂无周边信息"}

    {target_city}热门地点:
    {json.dumps(results.get('central_locations'), ensure_ascii=False, indent=2) if results.get('central_locations') else "暂无商业区域信息"}

    步行路线信息:
    {json.dumps(results.get('walking_routes'), ensure_ascii=False, indent=2) if results.get('walking_routes') else "暂无步行路线"}

    **请提供以下格式的详细建议：**

    ## 推荐会面地点

    ### 🎯 地点1: [具体地点名称]
    **选择理由：** [为什么选择这个地点]
    **地址：** [详细地址]
    **周边设施：** [餐饮、购物、娱乐等]

    #### 🚇 从地点A ({request.address1}) 出发：
    **详细路线：**
    1. 🚶‍♂️ 步行到最近地铁站：[站名] ([X]号出入口)
       - 步行距离：约[X]米
       - 步行时间：约[X]分钟
    
    2. 🚇 地铁路线：
       - 乘坐[地铁线路名称]，从[起始站]到[目标站]
       - 乘坐方向：往[终点站]方向
       - 乘坐时间：约[X]分钟 ([X]站)
       - 如需换乘：在[换乘站]换乘[线路名称]
    
    3. 🚶‍♂️ 到达目的地：
       - 从[地铁站名][X]号出口出站
       - 步行到目的地：约[X]米，[X]分钟
       - 具体步行路线：[详细描述]

    **⏱️ 总用时：约[X]分钟**
    **💰 地铁费用：约[X]元**

    #### 🚇 从地点B ({request.address2}) 出发：
    [按照同样格式提供详细路线]

    ### 🎯 地点2: [第二个推荐地点]
    [按照同样格式]

    ### 🎯 地点3: [第三个推荐地点]
    [按照同样格式]

    ## 📝 额外建议
    - **最佳会面时间：** [考虑交通高峰期]
    - **备选方案：** [如果主要路线有问题]
    - **注意事项：** [特殊提醒，如出入口、施工等]

    ## 🗺️ 地铁出入口指南
    [针对推荐地点，提供详细的地铁出入口信息，哪个出口最近，出来后往哪个方向走]

    请基于{target_city}的实际地铁网络和交通情况，提供准确详细的路线指导。每个步骤都要具体到地铁线路、站点、出入口编号、步行方向和时间。
    """

    try:
        model = genai.GenerativeModel('gemini-1.5-pro-latest')
        response = model.generate_content(prompt)
        
        return {
            "detailed_route_guide": response.text,
            "analysis_data": {
                "detected_city": target_city,
                "source_coordinates": {
                    "address1": f"{request.address1} -> {location1_coords}",
                    "address2": f"{request.address2} -> {location2_coords}",
                    "midpoint": results.get('midpoint')
                },
                "route_analysis": {
                    "transit_available": transit_available,
                    "nearby_pois_found": bool(results.get('nearby_pois')),
                    "central_locations_found": bool(results.get('central_locations')),
                    "walking_routes_available": bool(results.get('walking_routes'))
                }
            },
            "raw_mcp_data": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini API request failed: {e}")

# 调试端点
@app.get("/debug/available-tools")
async def debug_available_tools():
    """调试：获取MCP服务器上可用的工具"""
    async with MCPClient(AMAP_MCP_URL) as client:
        await client.initialize()
        tools = await client.get_available_tools()
        return tools

@app.get("/debug/test-geocode/{address}")
async def debug_test_geocode(address: str):
    """调试：测试地理编码功能"""
    result = await geocode_address(address)
    coords, city = extract_coordinates_and_city(result)
    return {
        "address": address,
        "geocode_result": result,
        "extracted_coordinates": coords,
        "detected_city": city
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
    return {"message": "Welcome to the MCP-powered Detailed Route Guide API!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
