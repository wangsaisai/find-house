import os
import json
import asyncio
import google.generativeai as genai
from typing import Dict, List, Any, Optional
import logging
from dotenv import load_dotenv
import aiohttp

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()

# 配置 Google Gemini API
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("No GOOGLE_API_KEY found in environment variables.")
genai.configure(api_key=GEMINI_API_KEY)

# 高德地图 MCP 服务器配置
AMAP_MCP_KEY = os.getenv("AMAP_MCP_KEY")
AMAP_MCP_URL = f"https://mcp.amap.com/mcp?key={AMAP_MCP_KEY}"

class MCPToolManager:
    """MCP工具管理器，负责与MCP服务器通信"""
    
    def __init__(self, url: str):
        self.url = url
        self.session = None
        self.request_id = 0
        self.available_tools = {}
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        await self.initialize()
        await self.load_available_tools()
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
                "capabilities": {"tools": {}},
                "clientInfo": {
                    "name": "intelligent-rental-analyzer",
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
                raise Exception("MCP initialization failed")
            result = await response.json()
            return result
    
    async def load_available_tools(self):
        """加载可用工具列表并构建工具描述"""
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
            if response.status == 200:
                result = await response.json()
                if "result" in result and "tools" in result["result"]:
                    for tool in result["result"]["tools"]:
                        self.available_tools[tool["name"]] = tool
                        logger.info(f"Loaded tool: {tool['name']}")
    
    async def call_tool(self, tool_name: str, arguments: dict):
        """调用指定的MCP工具"""
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
                return {"error": f"Failed to call tool {tool_name}"}
            result = await response.json()
            logger.info(f"Tool {tool_name} result received")
            return result
    
    def get_tools_description(self) -> str:
        """生成工具描述，供LLM理解可用工具"""
        descriptions = []
        for tool_name, tool_info in self.available_tools.items():
            desc = f"**{tool_name}**: {tool_info.get('description', '无描述')}"
            if 'inputSchema' in tool_info:
                schema = tool_info['inputSchema']
                if 'properties' in schema:
                    params = []
                    for param_name, param_info in schema['properties'].items():
                        param_desc = f"{param_name} ({param_info.get('type', 'unknown')})"
                        if param_info.get('description'):
                            param_desc += f": {param_info['description']}"
                        params.append(param_desc)
                    desc += f"\n  参数: {', '.join(params)}"
            descriptions.append(desc)
        return "\n\n".join(descriptions)

class IntelligentRentalAnalyzer:
    """智能租房位置分析器，使用LLM推理能力智能调用MCP工具"""
    
    def __init__(self):
        self.model = genai.GenerativeModel('gemini-2.5-pro')
        self.conversation_history = []
        self.analysis_data = {}
    
    async def analyze_rental_locations(self, work_address1: str, work_address2: str, 
                                     budget_range: str = "不限", preferences: str = "") -> Dict[str, Any]:
        """使用LLM推理能力进行智能租房分析"""
        
        async with MCPToolManager(AMAP_MCP_URL) as tool_manager:
            # 第一步：让LLM理解任务并制定分析计划
            initial_prompt = f"""
            我是一个智能租房位置分析助手。现在需要为用户找到最佳租房位置。

            **用户需求：**
            - 工作地点A: {work_address1}
            - 工作地点B: {work_address2}  
            - 预算范围: {budget_range}
            - 特殊偏好: {preferences if preferences else "无"}

            **可用的地图API工具：**
            {tool_manager.get_tools_description()}

            请根据用户需求，制定一个详细的分析计划。你需要：
            1. 分析需要收集哪些信息
            2. 确定需要调用哪些工具及其调用顺序
            3. 说明每个工具调用的目的和期望结果

            请用以下格式回答：
            ## 分析计划
            
            ### 第一阶段：基础信息收集
            - 工具名称：xxx
            - 调用目的：xxx
            - 预期结果：xxx
            
            ### 第二阶段：xxx
            ...
            
            请开始制定分析计划。
            """
            
            # 获取LLM的分析计划
            plan_response = self.model.generate_content(initial_prompt)
            analysis_plan = plan_response.text
            self.conversation_history.append(("plan", analysis_plan))
            logger.info(f"LLM制定的分析计划:\n{analysis_plan}")
            
            # 第二步：根据计划逐步执行分析
            return await self._execute_analysis_with_llm_guidance(
                tool_manager, work_address1, work_address2, budget_range, preferences
            )
    
    async def _execute_analysis_with_llm_guidance(self, tool_manager: MCPToolManager, 
                                                  work_address1: str, work_address2: str,
                                                  budget_range: str, preferences: str) -> Dict[str, Any]:
        """在LLM指导下执行分析"""
        
        analysis_results = {
            "work_address1": work_address1,
            "work_address2": work_address2,
            "budget_range": budget_range,
            "preferences": preferences,
            "tool_calls": [],
            "coordinates": {},
            "analysis_data": {}
        }
        
        max_iterations = 10  # 防止无限循环
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            
            # 询问LLM下一步应该做什么
            current_status = self._generate_current_status(analysis_results)
            
            next_step_prompt = f"""
            当前分析状态：
            {current_status}
            
            **已执行的工具调用：**
            {self._format_tool_calls_history(analysis_results["tool_calls"])}
            
            **可用工具：**
            {tool_manager.get_tools_description()}
            
            根据当前状态，请决定下一步行动：
            1. 如果需要调用工具，请用以下格式回答：
               ```
               CALL_TOOL
               工具名称: xxx
               参数: {{"param1": "value1", "param2": "value2"}}
               原因: xxx
               ```
            
            2. 如果信息收集完毕，可以进行最终分析，请回答：
               ```
               GENERATE_ANALYSIS
               原因: xxx
               ```
            
            3. 如果需要更多信息，请回答：
               ```
               NEED_MORE_INFO
               需要的信息: xxx
               建议的工具: xxx
               ```
            
            请分析当前情况并给出决策。
            """
            
            llm_decision = self.model.generate_content(next_step_prompt)
            decision_text = llm_decision.text.strip()
            
            logger.info(f"LLM决策 (第{iteration}轮): {decision_text}")
            
            # 解析LLM的决策
            if "CALL_TOOL" in decision_text:
                # 提取工具调用信息
                tool_call_info = self._parse_tool_call_decision(decision_text)
                if tool_call_info:
                    tool_name = tool_call_info["tool_name"]
                    arguments = tool_call_info["arguments"]
                    reason = tool_call_info["reason"]
                    
                    # 执行工具调用
                    try:
                        result = await tool_manager.call_tool(tool_name, arguments)
                        analysis_results["tool_calls"].append({
                            "tool_name": tool_name,
                            "arguments": arguments,
                            "result": result,
                            "reason": reason,
                            "iteration": iteration
                        })
                        
                        # 更新分析数据
                        self._update_analysis_data(analysis_results, tool_name, result)
                        
                        logger.info(f"成功执行工具调用: {tool_name}")
                        
                    except Exception as e:
                        logger.error(f"工具调用失败: {tool_name}, 错误: {e}")
                        analysis_results["tool_calls"].append({
                            "tool_name": tool_name,
                            "arguments": arguments,
                            "error": str(e),
                            "reason": reason,
                            "iteration": iteration
                        })
                
            elif "GENERATE_ANALYSIS" in decision_text:
                # 生成最终分析
                logger.info("LLM决定生成最终分析")
                final_analysis = await self._generate_final_analysis(analysis_results)
                analysis_results["final_analysis"] = final_analysis
                break
                
            elif "NEED_MORE_INFO" in decision_text:
                logger.info(f"LLM表示需要更多信息: {decision_text}")
                # 可以在这里添加处理逻辑
                
            else:
                logger.warning(f"无法解析LLM决策: {decision_text}")
                break
        
        return analysis_results
    
    def _parse_tool_call_decision(self, decision_text: str) -> Optional[Dict[str, Any]]:
        """解析LLM的工具调用决策"""
        try:
            lines = decision_text.split('\n')
            tool_name = None
            arguments = {}
            reason = ""
            
            for line in lines:
                line = line.strip()
                if line.startswith('工具名称:'):
                    tool_name = line.split(':', 1)[1].strip()
                elif line.startswith('参数:'):
                    param_str = line.split(':', 1)[1].strip()
                    try:
                        # 尝试解析JSON格式的参数
                        if param_str.startswith('{') and param_str.endswith('}'):
                            arguments = json.loads(param_str)
                        else:
                            # 如果不是JSON格式，尝试简单解析
                            arguments = {"query": param_str}
                    except json.JSONDecodeError:
                        arguments = {"query": param_str}
                elif line.startswith('原因:'):
                    reason = line.split(':', 1)[1].strip()
            
            if tool_name:
                return {
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "reason": reason
                }
            
        except Exception as e:
            logger.error(f"解析工具调用决策失败: {e}")
        
        return None
    
    def _update_analysis_data(self, analysis_results: Dict[str, Any], 
                             tool_name: str, result: Dict[str, Any]):
        """根据工具调用结果更新分析数据"""
        if tool_name == "maps_geo":
            # 地理编码结果
            coords, city = self._extract_coordinates_and_city(result)
            if coords:
                if "work_location1" not in analysis_results["coordinates"]:
                    analysis_results["coordinates"]["work_location1"] = coords
                    analysis_results["coordinates"]["city1"] = city
                elif "work_location2" not in analysis_results["coordinates"]:
                    analysis_results["coordinates"]["work_location2"] = coords
                    analysis_results["coordinates"]["city2"] = city
                
        elif tool_name in ["maps_direction_transit_integrated", "maps_direction_walking"]:
            # 路线信息
            if "routes" not in analysis_results["analysis_data"]:
                analysis_results["analysis_data"]["routes"] = []
            analysis_results["analysis_data"]["routes"].append(result)
            
        elif tool_name == "maps_around_search":
            # 周边搜索结果
            if "poi_data" not in analysis_results["analysis_data"]:
                analysis_results["analysis_data"]["poi_data"] = []
            analysis_results["analysis_data"]["poi_data"].append(result)
            
        elif tool_name == "maps_text_search":
            # 文本搜索结果
            if "search_results" not in analysis_results["analysis_data"]:
                analysis_results["analysis_data"]["search_results"] = []
            analysis_results["analysis_data"]["search_results"].append(result)
    
    def _extract_coordinates_and_city(self, geocode_result: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
        """从地理编码结果中提取坐标和城市信息"""
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
                                return location, detected_city
            return None, None
        except Exception as e:
            logger.error(f"提取坐标失败: {e}")
            return None, None
    
    def _generate_current_status(self, analysis_results: Dict[str, Any]) -> str:
        """生成当前分析状态的描述"""
        status_parts = []
        
        # 基本信息
        status_parts.append(f"目标: 为用户找到连接'{analysis_results['work_address1']}'和'{analysis_results['work_address2']}'的最佳租房位置")
        
        # 坐标信息
        coords = analysis_results["coordinates"]
        if coords:
            status_parts.append(f"已获取坐标: {len(coords)}个位置")
            for key, value in coords.items():
                if key.startswith("work_location"):
                    status_parts.append(f"  - {key}: {value}")
        else:
            status_parts.append("尚未获取工作地点坐标")
        
        # 工具调用统计
        tool_calls = analysis_results["tool_calls"]
        if tool_calls:
            status_parts.append(f"已执行工具调用: {len(tool_calls)}次")
            tool_summary = {}
            for call in tool_calls:
                tool_name = call["tool_name"]
                tool_summary[tool_name] = tool_summary.get(tool_name, 0) + 1
            for tool_name, count in tool_summary.items():
                status_parts.append(f"  - {tool_name}: {count}次")
        else:
            status_parts.append("尚未执行任何工具调用")
        
        # 分析数据统计
        analysis_data = analysis_results["analysis_data"]
        if analysis_data:
            status_parts.append("已收集的数据类型:")
            for data_type, data in analysis_data.items():
                if isinstance(data, list):
                    status_parts.append(f"  - {data_type}: {len(data)}条记录")
                else:
                    status_parts.append(f"  - {data_type}: 已收集")
        
        return "\n".join(status_parts)
    
    def _format_tool_calls_history(self, tool_calls: List[Dict[str, Any]]) -> str:
        """格式化工具调用历史"""
        if not tool_calls:
            return "无"
        
        formatted = []
        for i, call in enumerate(tool_calls, 1):
            formatted.append(f"{i}. {call['tool_name']}")
            formatted.append(f"   参数: {call['arguments']}")
            formatted.append(f"   原因: {call.get('reason', '未说明')}")
            if 'error' in call:
                formatted.append(f"   结果: 失败 - {call['error']}")
            else:
                formatted.append(f"   结果: 成功")
        
        return "\n".join(formatted)
    
    async def _generate_final_analysis(self, analysis_results: Dict[str, Any]) -> str:
        """生成最终的租房分析报告"""
        
        # 构建详细的数据总结给LLM
        data_summary = self._build_data_summary_for_llm(analysis_results)
        
        final_prompt = f"""
        基于收集到的所有数据，请生成一份详细的租房位置分析报告。

        **用户需求回顾：**
        - 工作地点A: {analysis_results['work_address1']}
        - 工作地点B: {analysis_results['work_address2']}
        - 预算范围: {analysis_results['budget_range']}
        - 特殊偏好: {analysis_results['preferences']}

        **收集到的数据：**
        {data_summary}

        请生成一份结构化的租房建议报告，包括：

        ## 🏠 推荐租房区域 (至少3个)

        ### 🌟 推荐区域1: [具体区域名称]
        **推荐理由：** [基于数据分析的推荐理由]
        **区域特点：** [区域环境描述]
        **预估租金：** [租金范围]
        **生活便利度：** ⭐⭐⭐⭐⭐

        #### 🚇 通勤分析
        - **到工作地点A**: [具体路线和时间]
        - **到工作地点B**: [具体路线和时间]

        #### 🏘️ 周边设施
        [基于收集的POI数据分析周边设施]

        ### 🌟 推荐区域2: [第二个区域]
        [类似结构]

        ### 🌟 推荐区域3: [第三个区域]
        [类似结构]

        ## 📊 综合分析

        ### 🎯 最佳选择
        [根据通勤便利性、生活便利性、经济性等因素综合评估]

        ### 💡 选房建议
        [基于分析数据的实用建议]

        ### ⚠️ 注意事项
        [需要注意的问题和风险]

        请确保所有建议都基于实际收集到的地图数据，提供具体且实用的信息。
        """
        
        try:
            response = self.model.generate_content(final_prompt)
            return response.text
        except Exception as e:
            logger.error(f"生成最终分析报告失败: {e}")
            return f"分析报告生成失败: {str(e)}"
    
    def _build_data_summary_for_llm(self, analysis_results: Dict[str, Any]) -> str:
        """为LLM构建数据总结"""
        summary_parts = []
        
        # 坐标信息
        coords = analysis_results["coordinates"]
        if coords:
            summary_parts.append("**坐标信息:**")
            for key, value in coords.items():
                summary_parts.append(f"- {key}: {value}")
        
        # 工具调用结果
        tool_calls = analysis_results["tool_calls"]
        if tool_calls:
            summary_parts.append("\n**工具调用结果:**")
            for call in tool_calls:
                summary_parts.append(f"- {call['tool_name']}: {call.get('reason', '数据收集')}")
                if 'result' in call and not call.get('error'):
                    # 简化结果显示
                    result_summary = self._summarize_tool_result(call['tool_name'], call['result'])
                    summary_parts.append(f"  结果: {result_summary}")
        
        # 分析数据
        analysis_data = analysis_results["analysis_data"]
        if analysis_data:
            summary_parts.append("\n**收集的分析数据:**")
            for data_type, data in analysis_data.items():
                summary_parts.append(f"- {data_type}: {self._summarize_data_type(data_type, data)}")
        
        return "\n".join(summary_parts)
    
    def _summarize_tool_result(self, tool_name: str, result: Dict[str, Any]) -> str:
        """总结工具调用结果"""
        try:
            if tool_name == "maps_geo":
                coords, city = self._extract_coordinates_and_city(result)
                return f"坐标: {coords}, 城市: {city}"
            elif "direction" in tool_name:
                return "路线信息已获取"
            elif "search" in tool_name:
                return "搜索结果已获取"
            else:
                return "数据已收集"
        except:
            return "已处理"
    
    def _summarize_data_type(self, data_type: str, data: Any) -> str:
        """总结数据类型"""
        if isinstance(data, list):
            return f"{len(data)}条记录"
        else:
            return "已收集"

# 使用示例
async def example_usage():
    """使用示例"""
    analyzer = IntelligentRentalAnalyzer()
    
    # 测试分析
    result = await analyzer.analyze_rental_locations(
        work_address1="北京市海淀区中关村大街1号",
        work_address2="北京市朝阳区国贸CBD",
        budget_range="5000-8000元",
        preferences="靠近地铁，环境安静"
    )
    
    print("智能分析结果:")
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    asyncio.run(example_usage())
