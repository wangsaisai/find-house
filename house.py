import os
import json
import asyncio
import google.generativeai as genai
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
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
    title="Optimal Rental Location Finder",
    description="An API to find the best rental location between two work/study addresses based on public transport convenience.",
    version="1.0.0"
)

# Mount the static directory to serve frontend files
app.mount("/static", StaticFiles(directory="static"), name="static")

class RentalLocationRequest(BaseModel):
    work_address1: str  # 第一个工作/学习地点
    work_address2: str  # 第二个工作/学习地点
    budget_range: str = "不限"  # 预算范围，可选
    preferences: str = ""  # 其他偏好，如：靠近地铁、环境安静等

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
                    "name": "rental-location-finder",
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

class RentalLocationAnalyzer:
    """租房位置分析器，帮助找到最佳租房地点"""
    
    def __init__(self):
        self.tools = {
            "geocode_address": geocode_address,
            "get_transit_directions": get_transit_directions,
            "get_walking_directions": get_walking_directions,
            "search_around": search_around,
            "text_search": text_search
        }
    
    async def analyze_rental_locations(self, work_address1: str, work_address2: str):
        """执行租房位置分析"""
        results = {}
        
        # 步骤1: 对两个工作地址进行地理编码
        logger.info("执行工作地址地理编码...")
        results['work_location1_result'] = await geocode_address(work_address1)
        results['work_location2_result'] = await geocode_address(work_address2)
        
        # 提取坐标和城市信息
        location1_coords, city1 = extract_coordinates_and_city(results['work_location1_result'])
        location2_coords, city2 = extract_coordinates_and_city(results['work_location2_result'])
        
        # 确定目标城市
        target_city = city1 or city2 or extract_city_from_address(work_address1) or extract_city_from_address(work_address2)
        
        logger.info(f"检测到的城市: city1={city1}, city2={city2}, target={target_city}")
        logger.info(f"提取的坐标: location1={location1_coords}, location2={location2_coords}")
        
        if not location1_coords or not location2_coords:
            logger.error("坐标提取失败")
            return results, location1_coords, location2_coords, target_city
        
        results['location1_coords'] = location1_coords
        results['location2_coords'] = location2_coords
        results['detected_city'] = target_city
        
        # 步骤2: 获取两个工作地点之间的公交路线信息
        logger.info("获取工作地点间的交通路线...")
        transit_attempts = [
            {"origin": location1_coords, "destination": location2_coords},
            {"origin": location1_coords, "destination": location2_coords, "city": target_city, "cityd": target_city} if target_city else None,
            {"origin": work_address1, "destination": work_address2},
            {"origin": work_address1, "destination": work_address2, "city": target_city, "cityd": target_city} if target_city else None
        ]
        
        transit_info = None
        for i, params in enumerate(transit_attempts):
            if params is None:
                continue
            try:
                logger.info(f"尝试交通路线查询方案 {i+1}: {params}")
                transit_info = await call_mcp_tool("maps_direction_transit_integrated", params)
                
                if transit_info and isinstance(transit_info, dict):
                    result_content = transit_info.get("result", {})
                    if not result_content.get("isError", True):
                        logger.info(f"交通路线查询成功，使用方案 {i+1}")
                        break
                    else:
                        logger.warning(f"方案 {i+1} 失败: {result_content}")
                        
            except Exception as e:
                logger.warning(f"交通路线查询方案 {i+1} 异常: {e}")
                continue
        
        results['transit_info'] = transit_info
        
        # 步骤3: 计算两个工作地点的中点
        midpoint = calculate_midpoint(location1_coords, location2_coords)
        results['midpoint'] = midpoint
        logger.info(f"计算的中点: {midpoint}")
        
        # 步骤4: 搜索中点周边的居住设施和生活便利设施
        logger.info("搜索中点周边的居住和生活设施...")
        results['residential_areas'] = await search_around(
            "住宅小区|公寓|租房", midpoint, "5000"  # 扩大搜索范围到5公里
        )
        
        results['life_facilities'] = await search_around(
            "超市|菜市场|医院|银行|购物中心", midpoint, "3000"
        )
        
        results['transport_hubs'] = await search_around(
            "地铁站|公交站", midpoint, "2000"
        )
        
        # 步骤5: 搜索目标城市的热门居住区域
        if target_city:
            logger.info(f"搜索{target_city}的热门居住区域...")
            if target_city == "北京":
                keywords = "回龙观|天通苑|望京|亚运村|西二旗|上地|五道口|中关村|国贸|朝阳公园"
            elif target_city == "上海":
                keywords = "浦东|徐汇|长宁|静安|黄浦|虹口|杨浦|闵行|宝山|松江"
            elif target_city == "广州":
                keywords = "天河|海珠|越秀|荔湾|白云|番禺|黄埔"
            elif target_city == "深圳":
                keywords = "南山|福田|罗湖|宝安|龙岗|龙华|坪山"
            elif target_city == "杭州":
                keywords = "西湖|上城|拱墅|余杭|滨江|萧山"
            else:
                keywords = "市中心|新区|开发区|大学城"
            
            results['popular_residential_areas'] = await text_search(f"{keywords}|住宅|小区", target_city, True)
        
        # 步骤6: 分析到各个工作地点的通勤路线
        commute_analysis = {}
        if results.get('residential_areas'):
            try:
                residential_content = results['residential_areas'].get('result', {}).get('content', [])
                if residential_content and len(residential_content) > 0:
                    residential_text = residential_content[0].get('text', '')
                    if residential_text:
                        residential_data = json.loads(residential_text)
                        areas = residential_data.get('pois', [])
                        
                        # 分析前3个住宅区的通勤情况
                        for area in areas[:3]:
                            area_name = area.get('name', '')
                            area_location = area.get('location', '')
                            if area_location:
                                try:
                                    # 获取从住宅区到两个工作地点的路线
                                    route_to_work1 = await get_transit_directions(area_location, location1_coords, target_city)
                                    route_to_work2 = await get_transit_directions(area_location, location2_coords, target_city)
                                    commute_analysis[area_name] = {
                                        'location': area_location,
                                        'to_work1': route_to_work1,
                                        'to_work2': route_to_work2
                                    }
                                except Exception as e:
                                    logger.warning(f"获取{area_name}的通勤路线失败: {e}")
            except Exception as e:
                logger.warning(f"解析住宅区域数据失败: {e}")
        
        results['commute_analysis'] = commute_analysis
        
        return results, location1_coords, location2_coords, target_city

@app.post("/find_rental_location")
async def find_rental_location(request: RentalLocationRequest):
    """
    使用 MCP 服务找到两个工作地点之间的最佳租房位置
    """
    logger.info(f"Processing rental location request for work addresses: {request.work_address1}, {request.work_address2}")
    
    # 使用租房位置分析器执行分析
    analyzer = RentalLocationAnalyzer()
    results, location1_coords, location2_coords, target_city = await analyzer.analyze_rental_locations(
        request.work_address1, request.work_address2
    )
    
    if not location1_coords or not location2_coords:
        return {
            "error": "Could not geocode one or both work addresses using MCP service.",
            "debug_info": results,
            "coordinates_debug": {
                "location1_coords": location1_coords,
                "location2_coords": location2_coords,
                "target_city": target_city
            }
        }
    
    # 检查交通信息是否可用
    transit_available = False
    transit_error = "暂无路线信息"
    if results.get('transit_info'):
        transit_result = results['transit_info'].get('result', {})
        if not transit_result.get('isError', True):
            transit_available = True
        else:
            content = transit_result.get('content', [])
            if content and len(content) > 0:
                transit_error = content[0].get('text', '交通路线查询失败')
    
    # 准备给 Gemini 的详细提示
    city_info = f"在{target_city}" if target_city else "在检测到的城市"
    budget_info = f"预算范围：{request.budget_range}" if request.budget_range != "不限" else "预算：无特殊限制"
    preferences_info = f"特殊偏好：{request.preferences}" if request.preferences else "无特殊偏好"
    
    prompt = f"""
    我需要为一个人找到{city_info}的最佳租房位置。这个人需要在两个不同的地点工作/学习，希望找到通勤便利、生活方便的租房区域。

    **工作地址信息：**
    - 工作地点A: {request.work_address1} (坐标: {location1_coords})
    - 工作地点B: {request.work_address2} (坐标: {location2_coords})
    - 检测城市: {target_city}
    - 两地中点坐标: {results.get('midpoint', '未计算')}
    - {budget_info}
    - {preferences_info}

    **通过高德地图API获取的数据：**

    两个工作地点间的交通信息:
    {"✅ 路线查询成功" if transit_available else f"❌ 路线查询失败: {transit_error}"}
    {json.dumps(results.get('transit_info'), ensure_ascii=False, indent=2) if transit_available else ""}

    中点附近的住宅区域:
    {json.dumps(results.get('residential_areas'), ensure_ascii=False, indent=2) if results.get('residential_areas') else "暂无住宅区域信息"}

    中点附近的生活设施:
    {json.dumps(results.get('life_facilities'), ensure_ascii=False, indent=2) if results.get('life_facilities') else "暂无生活设施信息"}

    中点附近的交通枢纽:
    {json.dumps(results.get('transport_hubs'), ensure_ascii=False, indent=2) if results.get('transport_hubs') else "暂无交通设施信息"}

    {target_city}热门居住区域:
    {json.dumps(results.get('popular_residential_areas'), ensure_ascii=False, indent=2) if results.get('popular_residential_areas') else "暂无热门居住区域信息"}

    通勤路线分析:
    {json.dumps(results.get('commute_analysis'), ensure_ascii=False, indent=2) if results.get('commute_analysis') else "暂无通勤路线分析"}

    **请提供以下格式的详细租房建议：**

    ## 🏠 推荐租房区域

    ### 🌟 推荐区域1: [具体区域名称]
    **推荐理由：** [为什么选择这个区域，通勤便利性分析]
    **区域特点：** [区域环境、房源类型、生活氛围等]
    **预估租金：** [根据区域给出大概租金范围]
    **生活便利度：** ⭐⭐⭐⭐⭐ (5星制)

    #### 🚇 到工作地点A ({request.work_address1}) 的通勤：
    **最佳通勤路线：**
    1. 🚶‍♂️ 步行到地铁站：[站名]
       - 步行距离：约[X]米，[X]分钟
    
    2. 🚇 地铁路线：
       - 乘坐[地铁线路]，从[起始站]到[目标站]
       - 乘坐时间：约[X]分钟 ([X]站)
       - 如需换乘：[详细换乘信息]
    
    3. 🚶‍♂️ 到达工作地点：
       - 从地铁站步行：约[X]分钟
    
    **⏱️ 总通勤时间：约[X]分钟**
    **💰 每日交通费：约[X]元**

    #### 🚇 到工作地点B ({request.work_address2}) 的通勤：
    **最佳通勤路线：**
    1. 🚶‍♂️ 步行到地铁站：[站名]
       - 步行距离：约[X]米，[X]分钟
    
    2. 🚇 地铁路线：
       - 乘坐[地铁线路]，从[起始站]到[目标站]
       - 乘坐时间：约[X]分钟 ([X]站)
       - 如需换乘：[详细换乘信息]
    
    3. 🚶‍♂️ 到达工作地点：
       - 从地铁站步行：约[X]分钟
    
    **⏱️ 总通勤时间：约[X]分钟**
    **💰 每日交通费：约[X]元**

    #### 🏘️ 周边生活设施：
    - **购物：** [超市、商场、菜市场等]
    - **餐饮：** [餐厅、小吃、外卖便利度]
    - **医疗：** [医院、药店、诊所]
    - **教育：** [学校、培训机构]
    - **娱乐：** [公园、健身房、影院等]
    - **银行：** [ATM、银行网点]

    #### 🏠 房源特点：
    - **主要房型：** [一居室、两居室、合租等]
    - **装修水平：** [简装、精装、豪装]
    - **配套设施：** [电梯、停车位、物业等]

    ### 🌟 推荐区域2: [第二个推荐区域]
    **推荐理由：** [为什么选择这个区域，通勤便利性分析]
    **区域特点：** [区域环境、房源类型、生活氛围等]
    **预估租金：** [根据区域给出大概租金范围]
    **生活便利度：** ⭐⭐⭐⭐⭐ (5星制)

    #### 🚇 到工作地点A ({request.work_address1}) 的通勤：
    **最佳通勤路线：**
    1. 🚶‍♂️ 步行到地铁站：[站名]
       - 步行距离：约[X]米，[X]分钟
    2. 🚇 地铁路线：
       - 乘坐[地铁线路]，从[起始站]到[目标站]
       - 乘坐时间：约[X]分钟 ([X]站)
       - 如需换乘：[详细换乘信息]
    3. 🚶‍♂️ 到达工作地点：
       - 从地铁站步行：约[X]分钟
    **⏱️ 总通勤时间：约[X]分钟**
    **💰 每日交通费：约[X]元**

    #### 🚇 到工作地点B ({request.work_address2}) 的通勤：
    **最佳通勤路线：**
    1. 🚶‍♂️ 步行到地铁站：[站名]
       - 步行距离：约[X]米，[X]分钟
    2. 🚇 地铁路线：
       - 乘坐[地铁线路]，从[起始站]到[目标站]
       - 乘坐时间：约[X]分钟 ([X]站)
       - 如需换乘：[详细换乘信息]
    3. 🚶‍♂️ 到达工作地点：
       - 从地铁站步行：约[X]分钟
    **⏱️ 总通勤时间：约[X]分钟**
    **💰 每日交通费：约[X]元**

    #### 🏘️ 周边生活设施：
    - **购物：** [超市、商场、菜市场等]
    - **餐饮：** [餐厅、小吃、外卖便利度]
    - **医疗：** [医院、药店、诊所]
    - **教育：** [学校、培训机构]
    - **娱乐：** [公园、健身房、影院等]
    - **银行：** [ATM、银行网点]

    #### 🏠 房源特点：
    - **主要房型：** [一居室、两居室、合租等]
    - **装修水平：** [简装、精装、豪装]
    - **配套设施：** [电梯、停车位、物业等]

    ### 🌟 推荐区域3: [第三个推荐区域]
    **推荐理由：** [为什么选择这个区域，通勤便利性分析]
    **区域特点：** [区域环境、房源类型、生活氛围等]
    **预估租金：** [根据区域给出大概租金范围]
    **生活便利度：** ⭐⭐⭐⭐⭐ (5星制)

    #### 🚇 到工作地点A ({request.work_address1}) 的通勤：
    **最佳通勤路线：**
    1. 🚶‍♂️ 步行到地铁站：[站名]
       - 步行距离：约[X]米，[X]分钟
    2. 🚇 地铁路线：
       - 乘坐[地铁线路]，从[起始站]到[目标站]
       - 乘坐时间：约[X]分钟 ([X]站)
       - 如需换乘：[详细换乘信息]
    3. 🚶‍♂️ 到达工作地点：
       - 从地铁站步行：约[X]分钟
    **⏱️ 总通勤时间：约[X]分钟**
    **💰 每日交通费：约[X]元**

    #### 🚇 到工作地点B ({request.work_address2}) 的通勤：
    **最佳通勤路线：**
    1. 🚶‍♂️ 步行到地铁站：[站名]
       - 步行距离：约[X]米，[X]分钟
    2. 🚇 地铁路线：
       - 乘坐[地铁线路]，从[起始站]到[目标站]
       - 乘坐时间：约[X]分钟 ([X]站)
       - 如需换乘：[详细换乘信息]
    3. 🚶‍♂️ 到达工作地点：
       - 从地铁站步行：约[X]分钟
    **⏱️ 总通勤时间：约[X]分钟**
    **💰 每日交通费：约[X]元**

    #### 🏘️ 周边生活设施：
    - **购物：** [超市、商场、菜市场等]
    - **餐饮：** [餐厅、小吃、外卖便利度]
    - **医疗：** [医院、药店、诊所]
    - **教育：** [学校、培训机构]
    - **娱乐：** [公园、健身房、影院等]
    - **银行：** [ATM、银行网点]

    #### 🏠 房源特点：
    - **主要房型：** [一居室、两居室、合租等]
    - **装修水平：** [简装、精装、豪装]
    - **配套设施：** [电梯、停车位、物业等]

    ## 📊 区域对比分析

    | 区域 | 通勤便利度 | 生活便利度 | 预估租金 | 环境质量 | 综合推荐度 |
    |------|-----------|-----------|----------|----------|-----------|
    | 区域1 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 中等 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
    | 区域2 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 较高 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
    | 区域3 | ⭐⭐⭐ | ⭐⭐⭐ | 较低 | ⭐⭐⭐ | ⭐⭐⭐ |

    ## 💡 租房实用建议

    ### 🔍 选房要点：
    - **交通优先：** [地铁线路选择建议]
    - **生活配套：** [必备周边设施]
    - **安全考虑：** [小区安全、周边环境]
    - **性价比：** [租金与便利度的平衡]

    ### ⏰ 通勤时间优化：
    - **避开高峰期建议：** [错峰出行时间]
    - **备选路线：** [主要路线拥堵时的替代方案]
    - **极端天气应对：** [雨雪天气的通勤建议]

    ### 💰 成本分析：
    - **每月交通费预估：** [两个工作地点的总交通费]
    - **生活成本：** [周边消费水平]
    - **隐性成本：** [通勤时间成本、体力成本等]

    ### 📋 看房清单：
    - [ ] 实地体验通勤路线
    - [ ] 检查手机信号和网络
    - [ ] 了解水电气暖费用
    - [ ] 查看周边夜间安全状况
    - [ ] 确认房东/中介资质

    ## 🗓️ 最佳找房时机
    [根据{target_city}的租房市场特点，建议最佳找房和搬家时间]

    请基于{target_city}的实际地铁网络、交通状况、住房市场和生活成本，提供准确详细的租房建议。重点关注通勤便利性、生活便利性和经济性的平衡。请确保为所有三个推荐区域都提供详细的通勤路线分析，不要省略任何一个。
    """

    try:
        model = genai.GenerativeModel('gemini-2.5-pro')
        response = model.generate_content(prompt)
        
        return {
            "rental_location_analysis": response.text,
            "analysis_data": {
                "detected_city": target_city,
                "work_coordinates": {
                    "work_address1": f"{request.work_address1} -> {location1_coords}",
                    "work_address2": f"{request.work_address2} -> {location2_coords}",
                    "midpoint": results.get('midpoint')
                },
                "user_preferences": {
                    "budget_range": request.budget_range,
                    "preferences": request.preferences
                },
                "analysis_summary": {
                    "transit_available": transit_available,
                    "residential_areas_found": bool(results.get('residential_areas')),
                    "life_facilities_found": bool(results.get('life_facilities')),
                    "transport_hubs_found": bool(results.get('transport_hubs')),
                    "popular_areas_found": bool(results.get('popular_residential_areas')),
                    "commute_analysis_available": bool(results.get('commute_analysis'))
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

@app.get("/debug/test-rental-analysis/{work_address1}/{work_address2}")
async def debug_test_rental_analysis(work_address1: str, work_address2: str):
    """调试：测试完整的租房分析计划"""
    analyzer = RentalLocationAnalyzer()
    results, coord1, coord2, city = await analyzer.analyze_rental_locations(work_address1, work_address2)
    return {
        "detected_city": city,
        "coordinates": {
            "work_location1": coord1,
            "work_location2": coord2
        },
        "analysis_results": results
    }

@app.get("/", response_class=FileResponse)
async def read_index():
    """Serves the frontend's index.html file."""
    return "static/index.html"

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
