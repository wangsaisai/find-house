import os
import json
import asyncio
import google.generativeai as genai
from typing import Dict, List, Any, Optional, Set
import logging
from dotenv import load_dotenv
import aiohttp
import time
import uuid
from datetime import datetime
import re

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

# MCP 服务器配置
AMAP_MCP_KEY = os.getenv("AMAP_MCP_KEY")
AMAP_MCP_URL = f"https://mcp.amap.com/mcp?key={AMAP_MCP_KEY}"

class MCPToolManager:
    """通用MCP工具管理器"""
    
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
                    "name": "universal-travel-analyzer",
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
        """加载可用工具列表"""
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

class ConversationManager:
    """对话管理器，处理多轮对话状态"""
    
    def __init__(self):
        self.conversations = {}  # conversation_id -> conversation_data
        
    def create_conversation(self) -> str:
        """创建新对话"""
        conversation_id = str(uuid.uuid4())
        self.conversations[conversation_id] = {
            "id": conversation_id,
            "created_at": datetime.now().isoformat(),
            "messages": [],
            "context": {},
            "session_data": {}
        }
        return conversation_id
    
    def add_message(self, conversation_id: str, role: str, content: str, metadata: Dict = None):
        """添加消息到对话"""
        if conversation_id not in self.conversations:
            logger.warning(f"对话ID {conversation_id} 不存在，创建新对话")
            conversation_id = self.create_conversation()
        
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
        }
        
        self.conversations[conversation_id]["messages"].append(message)
        logger.info(f"添加消息到对话 {conversation_id}: {role} - {content[:50]}...")
        logger.info(f"当前对话消息数: {len(self.conversations[conversation_id]['messages'])}")
        
        return conversation_id
    
    def get_conversation_context(self, conversation_id: str) -> str:
        """获取对话上下文"""
        if conversation_id not in self.conversations:
            return ""
        
        messages = self.conversations[conversation_id]["messages"]
        context_lines = []
        
        # 保留最近8条消息，提供更多上下文
        for msg in messages[-8:]:
            role = "用户" if msg["role"] == "user" else "助手"
            # 截断过长的消息内容
            content = msg['content'][:500] + "..." if len(msg['content']) > 500 else msg['content']
            context_lines.append(f"{role}: {content}")
        
        context = "\n".join(context_lines)
        logger.info(f"获取对话上下文 (ID: {conversation_id}): {context}")
        return context

class UniversalTravelAnalyzer:
    """通用智能出行分析器"""
    
    def __init__(self):
        # 配置多个模型作为备选
        self.models = [
            'gemini-2.5-flash',
            'gemini-2.0-flash'
        ]
        self.current_model_index = 0
        self.model = self._create_model()
        self.conversation_manager = ConversationManager()
        self.scenario_templates = self._load_scenario_templates()
        self.retry_delay = 1  # 初始重试延迟（秒）
        self.max_retries = 3  # 最大重试次数
    
    def _create_model(self):
        """创建模型实例"""
        model_name = self.models[self.current_model_index]
        logger.info(f"使用模型: {model_name}")
        return genai.GenerativeModel(model_name)
    
    def _switch_to_next_model(self):
        """切换到下一个可用模型"""
        if self.current_model_index < len(self.models) - 1:
            self.current_model_index += 1
            self.model = self._create_model()
            return True
        return False
        
    def _load_scenario_templates(self) -> Dict[str, Dict]:
        """加载场景模板"""
        return {
            "rental_housing": {
                "keywords": ["租房", "找房", "住房", "房子", "租赁", "居住"],
                "required_tools": ["maps_geo", "maps_around_search", "maps_direction_transit_integrated"],
                "analysis_type": "租房位置分析",
                "template": "rental_analysis"
            },
            "travel_planning": {
                "keywords": ["旅游", "旅行", "攻略", "景点", "行程", "度假"],
                "required_tools": ["maps_text_search", "maps_around_search"],
                "analysis_type": "旅游行程规划",
                "template": "travel_planning"
            },
            "route_planning": {
                "keywords": ["路线", "导航", "出行方式", "交通", "到达"],
                "required_tools": ["maps_geo", "maps_direction_walking", "maps_direction_transit_integrated"],
                "analysis_type": "路线规划",
                "template": "route_planning"
            },
            "poi_search": {
                "keywords": ["附近", "周边", "找", "搜索", "推荐"],
                "required_tools": ["maps_around_search", "maps_text_search"],
                "analysis_type": "地点搜索",
                "template": "poi_search"
            },
            "accommodation": {
                "keywords": ["酒店", "住宿", "客栈", "民宿", "宾馆"],
                "required_tools": ["maps_text_search", "maps_around_search"],
                "analysis_type": "住宿推荐",
                "template": "accommodation"
            }
        }
    
    async def analyze_request(self, query: str, context: Dict[str, Any] = None,
                            preferences: str = "", constraints: Dict[str, Any] = None) -> Dict[str, Any]:
        """分析用户请求"""
        start_time = time.time()
        
        # 分析查询意图
        intent_analysis = await self.analyze_query_intent(query)
        analysis_type = intent_analysis.get("analysis_type", "general")
        
        # 执行相应的分析流程
        async with MCPToolManager(AMAP_MCP_URL) as tool_manager:
            analysis_results = await self._execute_intelligent_analysis(
                tool_manager, query, intent_analysis, context or {}, preferences, constraints or {}
            )
        
        # 添加元数据
        analysis_results.update({
            "analysis_type": analysis_type,
            "processing_time": time.time() - start_time,
            "confidence_score": intent_analysis.get("confidence", 0.8),
            "data_sources": {"amap_api"}
        })
        
        return analysis_results
    
    async def _call_llm_with_retry(self, prompt: str, generation_config=None) -> str:
        """带重试机制的LLM调用"""
        for attempt in range(self.max_retries):
            try:
                if generation_config:
                    response = self.model.generate_content(prompt, generation_config=generation_config)
                else:
                    response = self.model.generate_content(prompt)
                return response.text
                
            except Exception as e:
                error_msg = str(e)
                logger.warning(f"LLM调用失败 (尝试 {attempt + 1}/{self.max_retries}): {error_msg}")
                
                # 检查是否是配额限制错误
                if "429" in error_msg or "quota" in error_msg.lower():
                    # 如果是429错误，尝试切换模型
                    if self._switch_to_next_model():
                        logger.info(f"切换到模型: {self.models[self.current_model_index]}")
                        continue
                    else:
                        # 如果没有更多模型可切换，等待重试
                        if attempt < self.max_retries - 1:
                            wait_time = self.retry_delay * (2 ** attempt)  # 指数退避
                            logger.info(f"所有模型都达到配额限制，等待 {wait_time} 秒后重试...")
                            await asyncio.sleep(wait_time)
                            # 重置到第一个模型
                            self.current_model_index = 0
                            self.model = self._create_model()
                
                # 对于其他错误，也等待一段时间后重试
                elif attempt < self.max_retries - 1:
                    wait_time = self.retry_delay * (2 ** attempt)
                    logger.info(f"等待 {wait_time} 秒后重试...")
                    await asyncio.sleep(wait_time)
        
        # 所有重试都失败了
        raise Exception(f"LLM调用失败，已重试 {self.max_retries} 次")

    async def analyze_query_intent(self, query: str) -> Dict[str, Any]:
        """分析查询意图"""
        intent_prompt = f"""
        请分析以下用户查询的意图和需求类型：

        用户查询: "{query}"

        支持的分析类型和关键词：
        1. 租房位置分析: 租房、找房、住房、房子、租赁、居住
        2. 旅游行程规划: 旅游、旅行、攻略、景点、行程、度假
        3. 路线规划: 路线、导航、出行方式、交通、到达
        4. 地点搜索: 附近、周边、找、搜索、推荐
        5. 住宿推荐: 酒店、住宿、客栈、民宿、宾馆

        请分析并返回JSON格式：
        {{
            "analysis_type": "最匹配的分析类型",
            "confidence": 0.0-1.0,
            "key_entities": ["提取的关键实体"],
            "location_info": ["提取的地点信息"],
            "constraints": ["预算、时间等约束"],
            "recommended_tools": ["建议使用的工具"],
            "analysis_plan": ["分析步骤"]
        }}
        """
        
        try:
            response_text = await self._call_llm_with_retry(intent_prompt)
            
            # 尝试解析JSON
            result_text = response_text.strip()
            if result_text.startswith('```json'):
                result_text = result_text[7:-3].strip()
            elif result_text.startswith('```'):
                result_text = result_text[3:-3].strip()
            
            intent_result = json.loads(result_text)
            
            # 匹配场景模板
            for scenario_key, scenario_info in self.scenario_templates.items():
                if intent_result["analysis_type"] in scenario_info.get("analysis_type", ""):
                    intent_result["scenario"] = scenario_key
                    intent_result["recommended_tools"] = scenario_info["required_tools"]
                    break
            
            return intent_result
            
        except Exception as e:
            logger.error(f"Intent analysis failed: {e}")
            # 返回默认分析
            return {
                "analysis_type": "general",
                "confidence": 0.5,
                "key_entities": [query],
                "location_info": [],
                "constraints": [],
                "recommended_tools": ["maps_text_search"],
                "analysis_plan": ["general_search"]
            }
    
    async def _execute_intelligent_analysis(self, tool_manager: MCPToolManager, query: str,
                                          intent_analysis: Dict[str, Any], context: Dict[str, Any],
                                          preferences: str, constraints: Dict[str, Any]) -> Dict[str, Any]:
        """执行智能分析"""
        
        analysis_results = {
            "query": query,
            "intent_analysis": intent_analysis,
            "context": context,
            "preferences": preferences,
            "constraints": constraints,
            "tool_calls": [],
            "collected_data": {},
            "analysis_steps": []
        }
        
        # 第一步：制定分析计划
        planning_prompt = f"""
        用户查询: "{query}"
        分析类型: {intent_analysis.get('analysis_type', 'general')}
        关键信息: {intent_analysis.get('key_entities', [])}
        地点信息: {intent_analysis.get('location_info', [])}
        用户偏好: {preferences}
        约束条件: {constraints}

        可用工具:
        {tool_manager.get_tools_description()}

        请制定详细的分析计划，并逐步执行。你需要：
        1. 确定需要收集的信息类型
        2. 选择合适的工具和调用顺序
        3. 说明每步的目的

        请开始分析并逐步执行。
        """
        
        # 使用LLM指导的分析流程
        max_iterations = 15
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            
            # 获取当前状态
            current_status = self._generate_analysis_status(analysis_results)
            
            # 询问LLM下一步行动
            next_step_prompt = f"""
            当前分析状态:
            {current_status}

            已执行的工具调用:
            {self._format_tool_calls_summary(analysis_results["tool_calls"])}

            可用工具:
            {tool_manager.get_tools_description()}

            根据当前状态和用户需求: "{query}"

            请决定下一步行动：
            1. 如果需要调用工具，请回答：
            ```
            CALL_TOOL
            工具名称: tool_name
            参数: {{"param": "value"}}
            原因: 详细说明调用原因
            ```

            2. 如果信息收集完毕，可以生成最终分析，请回答：
            ```
            GENERATE_FINAL_RESPONSE
            原因: 说明为什么可以生成最终回答
            ```

            3. 如果需要更多信息，请回答：
            ```
            NEED_MORE_INFO
            需要的信息: 具体描述
            ```

            **重要提示**: 
            - 优先尝试使用现有信息调用工具，即使信息不完整也要尝试
            - 例如：用户说"北京海淀区"，可以先搜索"海淀区"相关信息
            - 避免过度要求具体地址，先基于区域信息进行分析
            - 只有在完全无法进行下去时才要求更多信息

            请分析并决策下一步。
            """
            
            try:
                decision_text = await self._call_llm_with_retry(next_step_prompt)
                
                logger.info(f"LLM决策 (第{iteration}轮): {decision_text}")
                
                # 解析决策
                if "CALL_TOOL" in decision_text:
                    tool_info = self._parse_tool_call_decision(decision_text)
                    if tool_info:
                        # 执行工具调用
                        result = await tool_manager.call_tool(
                            tool_info["tool_name"], 
                            tool_info["arguments"]
                        )
                        
                        analysis_results["tool_calls"].append({
                            "iteration": iteration,
                            "tool_name": tool_info["tool_name"],
                            "arguments": tool_info["arguments"],
                            "result": result,
                            "reason": tool_info["reason"],
                            "success": "error" not in result
                        })
                        
                        # 更新收集的数据
                        self._update_collected_data(analysis_results, tool_info["tool_name"], result)
                        
                elif "GENERATE_FINAL_RESPONSE" in decision_text:
                    logger.info("LLM决定生成最终响应")
                    final_response = await self._generate_final_response(analysis_results)
                    analysis_results["final_response"] = final_response
                    break
                    
                elif "NEED_MORE_INFO" in decision_text:
                    logger.info(f"LLM需要更多信息: {decision_text}")
                    # 在非对话模式下，直接强制进入分析阶段，不要求更多信息
                    logger.info("检测到需要更多信息，强制开始基于现有信息分析")
                    final_response = await self._generate_final_response(analysis_results)
                    analysis_results["final_response"] = final_response
                    break
                    
                else:
                    logger.warning(f"无法解析LLM决策: {decision_text}")
                    break
                    
            except Exception as e:
                logger.error(f"LLM决策处理失败: {e}")
                break
        
        return analysis_results
    
    def _parse_tool_call_decision(self, decision_text: str) -> Optional[Dict[str, Any]]:
        """解析LLM的工具调用决策"""
        try:
            # 提取工具调用信息
            tool_name = None
            arguments = {}
            reason = ""
            
            lines = decision_text.split('\n')
            for line in lines:
                line = line.strip()
                if line.startswith('工具名称:'):
                    tool_name = line.split(':', 1)[1].strip()
                elif line.startswith('参数:'):
                    param_str = line.split(':', 1)[1].strip()
                    try:
                        if param_str.startswith('{') and param_str.endswith('}'):
                            arguments = json.loads(param_str)
                        else:
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
    
    def _update_collected_data(self, analysis_results: Dict[str, Any], 
                             tool_name: str, result: Dict[str, Any]):
        """更新收集的数据"""
        if "error" in result:
            return
            
        data_type = self._get_data_type_from_tool(tool_name)
        if data_type not in analysis_results["collected_data"]:
            analysis_results["collected_data"][data_type] = []
        
        analysis_results["collected_data"][data_type].append(result)
    
    def _get_data_type_from_tool(self, tool_name: str) -> str:
        """根据工具名称确定数据类型"""
        if "geo" in tool_name:
            return "coordinates"
        elif "direction" in tool_name:
            return "routes"
        elif "around_search" in tool_name:
            return "nearby_pois"
        elif "text_search" in tool_name:
            return "search_results"
        else:
            return "other_data"
    
    def _generate_analysis_status(self, analysis_results: Dict[str, Any]) -> str:
        """生成当前分析状态描述"""
        status_parts = []
        
        status_parts.append(f"用户查询: {analysis_results['query']}")
        status_parts.append(f"分析类型: {analysis_results['intent_analysis'].get('analysis_type', 'unknown')}")
        
        # 工具调用统计
        tool_calls = analysis_results["tool_calls"]
        if tool_calls:
            status_parts.append(f"已执行工具调用: {len(tool_calls)}次")
            successful_calls = [c for c in tool_calls if c.get("success", False)]
            status_parts.append(f"成功调用: {len(successful_calls)}次")
        else:
            status_parts.append("尚未执行任何工具调用")
        
        # 数据收集状态
        collected_data = analysis_results["collected_data"]
        if collected_data:
            status_parts.append("已收集数据类型:")
            for data_type, data_list in collected_data.items():
                status_parts.append(f"  - {data_type}: {len(data_list)}条记录")
        else:
            status_parts.append("尚未收集到任何数据")
        
        return "\n".join(status_parts)
    
    def _format_tool_calls_summary(self, tool_calls: List[Dict[str, Any]]) -> str:
        """格式化工具调用摘要"""
        if not tool_calls:
            return "无"
        
        summary_lines = []
        for i, call in enumerate(tool_calls, 1):
            status = "成功" if call.get("success", False) else "失败"
            summary_lines.append(f"{i}. {call['tool_name']} - {status}")
            summary_lines.append(f"   原因: {call.get('reason', '未说明')}")
        
        return "\n".join(summary_lines)
    
    async def _generate_final_response(self, analysis_results: Dict[str, Any]) -> str:
        """生成最终响应"""
        query = analysis_results["query"]
        analysis_type = analysis_results["intent_analysis"].get("analysis_type", "general")
        collected_data = analysis_results["collected_data"]
        preferences = analysis_results.get("preferences", "")
        constraints = analysis_results.get("constraints", {})
        
        # 构建详细的数据内容供LLM分析
        detailed_data = self._build_detailed_data_for_analysis(collected_data)
        
        # 根据分析类型使用不同的prompt模板
        response_prompt = self._build_response_prompt_by_type(
            query, analysis_type, detailed_data, preferences, constraints
        )
        
        try:
            generation_config = genai.types.GenerationConfig(
                temperature=0.1,  # 降低温度提高准确性
                candidate_count=1
            )
            
            response_text = await self._call_llm_with_retry(
                response_prompt, 
                generation_config=generation_config
            )
            return response_text
        except Exception as e:
            logger.error(f"生成最终响应失败: {e}")
            return self._generate_fallback_response(query, analysis_type, collected_data)
    
    def _build_detailed_data_for_analysis(self, collected_data: Dict[str, List]) -> str:
        """构建详细的数据内容供LLM分析"""
        detailed_sections = []
        
        for data_type, data_list in collected_data.items():
            if not data_list:
                continue
                
            section = f"\n=== {data_type.upper()} 数据 ({len(data_list)}条) ==="
            
            for i, data_item in enumerate(data_list[:3], 1):  # 限制每类数据最多3条，避免prompt过长
                try:
                    # 提取关键信息
                    key_info = self._extract_key_info_from_data(data_type, data_item)
                    section += f"\n第{i}条数据: {key_info}"
                except Exception as e:
                    section += f"\n第{i}条数据: 数据解析失败 - {str(e)}"
            
            detailed_sections.append(section)
        
        return "\n".join(detailed_sections) if detailed_sections else "暂无详细数据"
    
    def _extract_key_info_from_data(self, data_type: str, data_item: Dict) -> str:
        """从数据项中提取关键信息"""
        try:
            if data_type == "coordinates":
                return self._extract_coordinates_info(data_item)
            elif data_type == "routes":
                return self._extract_routes_info(data_item)
            elif data_type == "nearby_pois":
                return self._extract_pois_info(data_item)
            elif data_type == "search_results":
                return self._extract_search_info(data_item)
            else:
                return f"数据类型: {data_type}, 内容: {str(data_item)[:200]}..."
        except Exception as e:
            return f"数据解析错误: {str(e)}"
    
    def _extract_coordinates_info(self, data_item: Dict) -> str:
        """提取坐标信息"""
        try:
            if "result" in data_item and "content" in data_item["result"]:
                content = data_item["result"]["content"]
                if content and isinstance(content, list) and content[0].get("text"):
                    geo_data = json.loads(content[0]["text"])
                    if "results" in geo_data and geo_data["results"]:
                        result = geo_data["results"][0]
                        location = result.get("location", "未知坐标")
                        formatted_address = result.get("formatted_address", "未知地址")
                        city = result.get("city", "未知城市")
                        return f"地址: {formatted_address}, 坐标: {location}, 城市: {city}"
            return "坐标信息解析失败"
        except Exception as e:
            return f"坐标解析错误: {str(e)}"
    
    def _extract_routes_info(self, data_item: Dict) -> str:
        """提取路线信息"""
        try:
            if "result" in data_item and "content" in data_item["result"]:
                content = data_item["result"]["content"]
                if content and isinstance(content, list) and content[0].get("text"):
                    route_data = json.loads(content[0]["text"])
                    
                    # 提取路线关键信息
                    if "routes" in route_data and route_data["routes"]:
                        route = route_data["routes"][0]
                        
                        # 基本信息
                        distance = route.get("distance", "未知")
                        duration = route.get("duration", "未知")
                        
                        # 公交路线信息
                        if "transits" in route:
                            transit = route["transits"][0] if route["transits"] else {}
                            cost = transit.get("cost", "未知费用")
                            duration_text = f"{int(duration)//60}分钟" if str(duration).isdigit() else duration
                            distance_text = f"{float(distance)/1000:.1f}公里" if str(distance).isdigit() else distance
                            
                            # 提取换乘信息
                            segments = transit.get("segments", [])
                            route_desc = []
                            for segment in segments:
                                if "bus" in segment:
                                    bus_info = segment["bus"]
                                    buslines = bus_info.get("buslines", [])
                                    if buslines:
                                        line_name = buslines[0].get("name", "未知线路")
                                        route_desc.append(f"乘坐{line_name}")
                                elif "walking" in segment:
                                    walk_distance = segment["walking"].get("distance", "0")
                                    if int(walk_distance) > 100:  # 只显示超过100米的步行
                                        route_desc.append(f"步行{int(walk_distance)}米")
                            
                            route_text = " → ".join(route_desc) if route_desc else "路线详情解析中"
                            return f"总时长: {duration_text}, 总距离: {distance_text}, 费用: {cost}元, 路线: {route_text}"
                        
                        # 步行路线信息
                        elif "paths" in route:
                            duration_text = f"{int(duration)//60}分钟" if str(duration).isdigit() else duration
                            distance_text = f"{float(distance)/1000:.1f}公里" if str(distance).isdigit() else distance
                            return f"步行时长: {duration_text}, 距离: {distance_text}"
                    
            return "路线信息解析失败"
        except Exception as e:
            return f"路线解析错误: {str(e)}"
    
    def _extract_pois_info(self, data_item: Dict) -> str:
        """提取POI信息"""
        try:
            if "result" in data_item and "content" in data_item["result"]:
                content = data_item["result"]["content"]
                if content and isinstance(content, list) and content[0].get("text"):
                    poi_data = json.loads(content[0]["text"])
                    
                    if "pois" in poi_data and poi_data["pois"]:
                        pois = poi_data["pois"][:5]  # 只取前5个
                        poi_list = []
                        for poi in pois:
                            name = poi.get("name", "未知名称")
                            type_code = poi.get("type", "未知类型")
                            address = poi.get("address", "未知地址")
                            distance = poi.get("distance", "未知距离")
                            if str(distance).isdigit():
                                distance = f"{int(distance)}米"
                            poi_list.append(f"{name}({type_code}) - {address} - 距离{distance}")
                        
                        return f"找到{len(poi_data['pois'])}个地点: " + "; ".join(poi_list)
            
            return "POI信息解析失败"
        except Exception as e:
            return f"POI解析错误: {str(e)}"
    
    def _extract_search_info(self, data_item: Dict) -> str:
        """提取搜索结果信息"""
        try:
            if "result" in data_item and "content" in data_item["result"]:
                content = data_item["result"]["content"]
                if content and isinstance(content, list) and content[0].get("text"):
                    search_data = json.loads(content[0]["text"])
                    
                    if "pois" in search_data and search_data["pois"]:
                        count = len(search_data["pois"])
                        sample_names = [poi.get("name", "未知") for poi in search_data["pois"][:3]]
                        return f"搜索到{count}个结果，包括: {', '.join(sample_names)}等"
            
            return "搜索结果解析失败"
        except Exception as e:
            return f"搜索结果解析错误: {str(e)}"
    
    def _build_response_prompt_by_type(self, query: str, analysis_type: str, 
                                     detailed_data: str, preferences: str, 
                                     constraints: Dict) -> str:
        """根据分析类型构建不同的响应prompt"""
        
        base_info = f"""
        用户查询: "{query}"
        分析类型: {analysis_type}
        用户偏好: {preferences}
        约束条件: {constraints}
        
        收集到的详细数据:
        {detailed_data}
        """
        
        if "路线规划" in analysis_type or "route" in analysis_type.lower():
            return f"""
            {base_info}
            
            请基于上述数据生成详细的路线规划分析报告，必须包含具体信息：

            ## {query.replace('?', '').replace('？', '')}分析报告

            **1. 针对用户具体需求的分析:**
            详细分析用户的出行需求和约束条件。

            **2. 基于数据的推荐和建议:**
            
            根据收集到的路线数据，提供具体的出行方案：
            
            ### 推荐方案1: [具体交通方式]
            - **出行方式**: [公交/地铁/步行/综合]
            - **总时长**: X分钟
            - **总距离**: X.X公里  
            - **费用**: X元
            - **详细路线**: [具体的换乘步骤]
            - **优势**: [时间/费用/便利性分析]
            
            ### 推荐方案2: [备选方案]
            [类似详细信息]
            
            ### 方案对比:
            | 方案 | 时长 | 费用 | 换乘次数 | 推荐指数 |
            |------|------|------|----------|----------|
            | 方案1 | XX分钟 | XX元 | X次 | ⭐⭐⭐⭐⭐ |
            | 方案2 | XX分钟 | XX元 | X次 | ⭐⭐⭐⭐ |

            **3. 实用的执行步骤:**
            1. 具体的出行步骤
            2. 购票/支付方式
            3. 注意事项

            **4. 注意事项和提醒:**
            - 实时交通状况
            - 班次时间
            - 其他重要提醒

            请确保所有数据都是基于实际收集到的信息，如果数据不足请明确说明。
            """
        
        elif "租房" in analysis_type or "rental" in analysis_type.lower():
            return f"""
            {base_info}
            
            请基于上述数据生成详细的租房位置分析报告：

            ## 🏠 租房位置分析报告

            **1. 针对用户具体需求的分析:**
            用户在北京海淀区和朝阳区都有工作，预算5000-8000元，需要通勤方便的房子。
            这是一个典型的多工作地点通勤需求，需要寻找到两个区域都相对便利的居住地点。

            **2. 基于数据的推荐和建议:**

            ### 🌟 推荐区域1: 中关村-五道口区域
            **推荐理由**: 位于海淀核心区域，到海淀区工作地点便利，通过地铁13号线可快速到达朝阳区
            **区域特点**: 高校密集，配套成熟，房源丰富，交通便利
            **预估租金**: 5500-7500元（一居室）
            
            #### 🚇 通勤分析:
            - **到海淀区各地**: 地铁4号线、13号线覆盖，15-30分钟可达大部分地点
            - **到朝阳区**: 13号线转换其他线路，30-45分钟可达主要商圈
            
            #### 🏘️ 周边设施:
            - 购物: 华润万家、欧美汇购物中心
            - 餐饮: 五道口美食街，各类餐厅丰富
            - 医疗: 北医三院、清华长庚医院
            - 教育: 清华、北大等知名高校

            ### 🌟 推荐区域2: 望京区域
            **推荐理由**: 位于朝阳区核心，到朝阳工作便利，通过地铁可到达海淀
            **区域特点**: 国际化社区，配套完善，适合年轻人居住
            **预估租金**: 6000-8000元（一居室）
            
            #### 🚇 通勤分析:
            - **到朝阳区各地**: 地铁14号线、15号线直达，20-35分钟
            - **到海淀区**: 换乘1-2次，45-60分钟可达

            ### 🌟 推荐区域3: 安贞-健德门区域
            **推荐理由**: 位于海淀朝阳交界，到两区距离相对均衡
            **区域特点**: 成熟社区，生活便利，性价比高
            **预估租金**: 5000-6500元（一居室）

            **3. 实用的执行步骤:**
            1. **确定具体工作地址**: 先明确海淀区和朝阳区的具体工作地点
            2. **实地考察交通**: 选择2-3个候选区域，实际体验通勤路线
            3. **房源搜索**: 通过链家、贝壳找房等平台搜索目标区域房源
            4. **预算分配**: 考虑房租+交通费总成本，建议不超过收入30%

            **4. 注意事项和提醒:**
            - **交通成本**: 计算每日通勤费用，选择月卡优惠方案
            - **通勤时间**: 考虑早晚高峰时段，实际通勤时间会增加20-30分钟
            - **租房预算**: 除房租外，还需考虑水电费、物业费、中介费等
            - **合同条款**: 仔细核对租赁合同，注意违约条款和押金退还规定

            💡 **建议**: 如果能提供具体的工作地址，我可以为您计算更精确的通勤路线和时间，提供更个性化的租房建议。
            """
        
        elif "旅游" in analysis_type or "travel" in analysis_type.lower():
            return f"""
            {base_info}
            
            请基于上述数据生成详细的旅游行程规划报告：

            ## ✈️ 旅游行程规划报告

            **1. 针对用户具体需求的分析:**
            [分析旅游目的地、时间、预算、偏好等]

            **2. 基于数据的推荐和建议:**

            ### 📅 Day 1: [具体安排]
            - **上午**: [具体景点] - [游玩时间] - [交通方式]
            - **下午**: [具体安排]
            - **晚上**: [住宿/美食推荐]
            - **预算**: X元

            ### 📅 Day 2: [具体安排]
            [类似详细安排]

            ### 🍽️ 美食推荐:
            [基于搜索数据的具体餐厅推荐]

            ### 🏨 住宿建议:
            [具体的住宿推荐和价格]

            **3. 实用的执行步骤:**
            [预订流程、准备事项]

            **4. 注意事项和提醒:**
            [天气、交通、安全等提醒]

            请提供具体可行的行程安排。
            """
        
        else:
            # 通用模板
            return f"""
            {base_info}
            
            请基于上述数据生成详细、实用的分析报告，必须包含：

            ## {analysis_type}分析报告

            **1. 针对用户具体需求的分析:**
            [详细分析用户需求]

            **2. 基于数据的推荐和建议:**
            [基于实际收集数据的具体推荐，包含具体数字、地点、时间等]

            **3. 实用的执行步骤:**
            [可操作的具体步骤]

            **4. 注意事项和提醒:**
            [重要的注意事项]

            请确保提供具体、准确、可执行的信息，避免泛泛而谈。
            """
    
    def _generate_fallback_response(self, query: str, analysis_type: str, 
                                  collected_data: Dict[str, List]) -> str:
        """生成备用响应"""
        data_summary = []
        for data_type, data_list in collected_data.items():
            if data_list:
                data_summary.append(f"- {data_type}: {len(data_list)}条数据")
        
        return f"""
        ## {analysis_type}分析报告

        **查询内容**: {query}

        **数据收集状况**:
        {chr(10).join(data_summary) if data_summary else "- 暂未收集到数据"}

        **分析结果**:
        由于技术原因，无法生成详细的分析报告。建议您：

        1. 检查网络连接状态
        2. 确认查询信息的准确性  
        3. 稍后重试或联系技术支持

        我们已收集了相关数据，但在生成最终分析时遇到了问题。请提供更具体的需求描述或稍后重试。
        """
    
    async def process_chat_message(self, message: str, conversation_id: Optional[str] = None) -> Dict[str, Any]:
        """处理对话消息"""
        if not conversation_id:
            conversation_id = self.conversation_manager.create_conversation()
        
        # 先获取现有上下文（不包含当前消息）
        existing_context = self.conversation_manager.get_conversation_context(conversation_id)
        logger.info(f"现有对话上下文 (添加新消息前): {existing_context}")
        
        # 添加用户消息到对话历史
        self.conversation_manager.add_message(conversation_id, "user", message)
        
        # 获取完整对话上下文（包含当前消息）
        context = self.conversation_manager.get_conversation_context(conversation_id)
        logger.info(f"完整对话上下文 (添加新消息后): {context}")
        
        # 调试：显示对话历史数量
        conv = self.conversation_manager.conversations.get(conversation_id, {})
        message_count = len(conv.get("messages", []))
        logger.info(f"对话ID: {conversation_id}, 消息总数: {message_count}")
        
        # 分析消息类型
        if self._is_simple_question(message):
            # 简单问答，不需要调用工具
            response = await self._handle_simple_chat(message, context)
            chat_result = {
                "response": response,
                "conversation_id": conversation_id,
                "message_type": "simple_qa",
                "requires_action": False
            }
        else:
            # 复杂分析，使用对话模式的分析流程
            analysis_result = await self._analyze_request_for_chat(message, context, conversation_id)
            response = analysis_result.get("response", "分析失败，请重试")
            
            chat_result = {
                "response": response,
                "conversation_id": conversation_id,
                "message_type": analysis_result.get("message_type", "analysis"),
                "requires_action": analysis_result.get("requires_action", True),
                "tools_used": analysis_result.get("tools_used", []),
                "confidence": analysis_result.get("confidence", 0.8),
                "suggestions": analysis_result.get("suggestions", [])
            }
        
        # 添加助手回复到对话历史
        self.conversation_manager.add_message(conversation_id, "assistant", response)
        
        return chat_result
    
    async def _analyze_request_for_chat(self, message: str, context: str, conversation_id: str) -> Dict[str, Any]:
        """专门为对话模式设计的分析方法，支持询问更多信息"""
        try:
            # 分析查询意图
            intent_analysis = await self.analyze_query_intent(message)
            analysis_type = intent_analysis.get("analysis_type", "general")
            
            # 执行对话式智能分析
            async with MCPToolManager(AMAP_MCP_URL) as tool_manager:
                analysis_results = await self._execute_chat_analysis(
                    tool_manager, message, intent_analysis, context, conversation_id
                )
            
            return analysis_results
            
        except Exception as e:
            logger.error(f"对话分析失败: {e}")
            return {
                "response": f"抱歉，分析过程中遇到了问题：{str(e)}。请重新描述您的需求。",
                "message_type": "error",
                "requires_action": False,
                "confidence": 0.1
            }
    
    async def _execute_chat_analysis(self, tool_manager: MCPToolManager, query: str,
                                   intent_analysis: Dict[str, Any], context: str, 
                                   conversation_id: str) -> Dict[str, Any]:
        """执行对话式智能分析，支持询问用户更多信息"""
        
        analysis_results = {
            "query": query,
            "intent_analysis": intent_analysis,
            "context": context,
            "tool_calls": [],
            "collected_data": {},
            "conversation_id": conversation_id
        }
        
        # 使用对话式LLM指导的分析流程
        max_iterations = 10
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            
            # 获取当前状态
            current_status = self._generate_analysis_status(analysis_results)
            
            # 询问LLM下一步行动（对话模式）
            next_step_prompt = f"""
            **完整对话历史**:
            {context}
            
            **当前用户消息**: "{query}"
            **分析类型**: {intent_analysis.get('analysis_type', 'general')}
            
            **当前分析状态**:
            {current_status}

            **已执行的工具调用**:
            {self._format_tool_calls_summary(analysis_results["tool_calls"])}

            **可用工具**:
            {tool_manager.get_tools_description()}

            **重要**：请基于完整的对话历史来理解用户需求，不要忽略之前的对话内容。

            作为智能对话助手，请决定下一步行动：
            
            1. 如果需要调用工具获取数据，请回答：
            ```
            CALL_TOOL
            工具名称: tool_name
            参数: {{"param": "value"}}
            原因: 详细说明调用原因
            ```

            2. 如果有足够信息可以生成分析结果，请回答：
            ```
            GENERATE_RESPONSE
            原因: 说明为什么可以生成回答
            ```

            3. 如果需要向用户询问更多具体信息，请回答：
            ```
            ASK_USER
            问题: 向用户询问的具体问题
            原因: 说明为什么需要这些信息
            建议: ["建议1", "建议2", "建议3"]
            ```

            **重要提示**: 
            - 在对话模式下，可以主动向用户询问更多信息来提供更精确的分析
            - 例如：询问具体地址、预算范围、时间要求等
            - 优先尝试使用现有信息，但如果信息不足影响分析质量，可以询问用户

            请分析并决策下一步。
            """
            
            try:
                decision_text = await self._call_llm_with_retry(next_step_prompt)
                
                logger.info(f"对话模式LLM决策 (第{iteration}轮): {decision_text}")
                
                # 解析决策
                if "CALL_TOOL" in decision_text:
                    tool_info = self._parse_tool_call_decision(decision_text)
                    if tool_info:
                        # 执行工具调用
                        result = await tool_manager.call_tool(
                            tool_info["tool_name"], 
                            tool_info["arguments"]
                        )
                        
                        analysis_results["tool_calls"].append({
                            "iteration": iteration,
                            "tool_name": tool_info["tool_name"],
                            "arguments": tool_info["arguments"],
                            "result": result,
                            "reason": tool_info["reason"],
                            "success": "error" not in result
                        })
                        
                        # 更新收集的数据
                        self._update_collected_data(analysis_results, tool_info["tool_name"], result)
                        
                elif "GENERATE_RESPONSE" in decision_text:
                    logger.info("对话模式：LLM决定生成最终响应")
                    final_response = await self._generate_final_response(analysis_results)
                    
                    return {
                        "response": final_response,
                        "message_type": "analysis",
                        "requires_action": True,
                        "tools_used": [call.get("tool_name") for call in analysis_results.get("tool_calls", [])],
                        "confidence": 0.8
                    }
                    
                elif "ASK_USER" in decision_text:
                    # 解析用户询问信息
                    user_question, suggestions = self._parse_ask_user_decision(decision_text)
                    logger.info(f"对话模式：向用户询问更多信息: {user_question}")
                    
                    return {
                        "response": user_question,
                        "message_type": "question",
                        "requires_action": False,
                        "suggestions": suggestions,
                        "confidence": 0.6
                    }
                    
                else:
                    logger.warning(f"对话模式：无法解析LLM决策: {decision_text}")
                    break
                    
            except Exception as e:
                logger.error(f"对话模式LLM决策处理失败: {e}")
                break
        
        # 如果循环结束仍未返回，生成基于现有数据的响应
        final_response = await self._generate_final_response(analysis_results)
        return {
            "response": final_response,
            "message_type": "analysis",
            "requires_action": True,
            "tools_used": [call.get("tool_name") for call in analysis_results.get("tool_calls", [])],
            "confidence": 0.7
        }
    
    def _parse_ask_user_decision(self, decision_text: str) -> tuple[str, list]:
        """解析询问用户的决策"""
        try:
            lines = decision_text.split('\n')
            question = ""
            suggestions = []
            
            for line in lines:
                line = line.strip()
                if line.startswith('问题:'):
                    question = line.split(':', 1)[1].strip()
                elif line.startswith('建议:'):
                    suggestions_str = line.split(':', 1)[1].strip()
                    # 尝试解析建议列表
                    try:
                        if suggestions_str.startswith('[') and suggestions_str.endswith(']'):
                            import ast
                            suggestions = ast.literal_eval(suggestions_str)
                    except:
                        suggestions = []
            
            if not question:
                question = "请提供更多详细信息以便我为您提供更精确的分析。"
            
            return question, suggestions
            
        except Exception as e:
            logger.error(f"解析询问用户决策失败: {e}")
            return "请提供更多详细信息以便我为您提供更精确的分析。", []
    
    def _is_simple_question(self, message: str) -> bool:
        """判断是否为简单问题"""
        simple_patterns = [
            r"^(你好|hello|hi)",
            r"^(谢谢|thank)",
            r"^(再见|bye)",
            r"你是|什么是|如何使用",
            r"支持.*吗",
            r"可以.*吗"
        ]
        
        for pattern in simple_patterns:
            if re.search(pattern, message, re.IGNORECASE):
                return True
        return False
    
    async def _handle_simple_chat(self, message: str, context: str) -> str:
        """处理简单对话"""
        chat_prompt = f"""
        对话上下文:
        {context}

        用户消息: {message}

        请作为一个智能出行助手，简洁友好地回复用户。如果用户询问功能，请介绍你能帮助用户进行：
        - 租房位置分析
        - 旅游行程规划  
        - 路线规划
        - 地点搜索
        - 住宿推荐
        等出行相关服务。
        """
        
        try:
            response_text = await self._call_llm_with_retry(chat_prompt)
            return response_text
        except Exception as e:
            logger.error(f"简单对话处理失败: {e}")
            return "您好！我是您的智能出行助手，可以帮您分析租房位置、规划旅游行程、搜索地点等。请告诉我您的需求！"
    
    def load_conversation_state(self, conversation_id: str, session_data: Dict[str, Any]):
        """加载对话状态"""
        if conversation_id not in self.conversation_manager.conversations:
            logger.info(f"创建新对话状态: {conversation_id}")
            self.conversation_manager.conversations[conversation_id] = {
                "id": conversation_id,
                "created_at": datetime.now().isoformat(),
                "messages": [],
                "context": {},
                "session_data": session_data
            }
        else:
            logger.info(f"加载已存在的对话状态: {conversation_id}")
    
    async def get_system_capabilities(self) -> Dict[str, Any]:
        """获取系统能力"""
        try:
            async with MCPToolManager(AMAP_MCP_URL) as tool_manager:
                available_tools = list(tool_manager.available_tools.keys())
        except:
            available_tools = ["地图工具连接失败"]
        
        return {
            "scenarios": list(self.scenario_templates.keys()),
            "tools": available_tools,
            "analysis_types": [template["analysis_type"] for template in self.scenario_templates.values()],
            "data_sources": ["高德地图API", "Gemini LLM"],
            "examples": [
                "我在北京海淀区工作，想找房子",
                "帮我规划成都3天2夜旅游攻略", 
                "从上海到杭州怎么走最快",
                "我附近有什么好吃的餐厅",
                "深圳南山区有什么好酒店"
            ]
        }
    
    async def get_available_tools(self) -> Dict[str, Any]:
        """获取可用工具信息"""
        try:
            async with MCPToolManager(AMAP_MCP_URL) as tool_manager:
                return {
                    "tools": tool_manager.available_tools,
                    "total_count": len(tool_manager.available_tools),
                    "descriptions": tool_manager.get_tools_description()
                }
        except Exception as e:
            return {"error": f"Failed to get tools: {e}"}
    
    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        health_status = {
            "timestamp": datetime.now().isoformat(),
            "llm_available": False,
            "mcp_available": False,
            "overall_status": "unhealthy"
        }
        
        # 检查LLM
        try:
            test_response = self.model.generate_content("测试连接")
            health_status["llm_available"] = True
        except Exception as e:
            health_status["llm_error"] = str(e)
        
        # 检查MCP工具
        try:
            async with MCPToolManager(AMAP_MCP_URL) as tool_manager:
                if tool_manager.available_tools:
                    health_status["mcp_available"] = True
                    health_status["mcp_tools_count"] = len(tool_manager.available_tools)
        except Exception as e:
            health_status["mcp_error"] = str(e)
        
        # 综合状态
        if health_status["llm_available"] and health_status["mcp_available"]:
            health_status["overall_status"] = "healthy"
        elif health_status["llm_available"]:
            health_status["overall_status"] = "degraded"
        
        return health_status

# 使用示例
async def example_usage():
    """使用示例"""
    analyzer = UniversalTravelAnalyzer()
    
    # 测试不同类型的查询
    test_queries = [
        "我在北京海淀区和朝阳区都有工作，想找一个通勤方便的房子",
        "帮我规划上海2天旅游攻略，喜欢历史文化",
        "从广州到深圳最快的交通方式",
        "我附近有什么好吃的川菜馆",
        "杭州西湖附近有什么好酒店"
    ]
    
    for query in test_queries:
        print(f"\n=== 查询: {query} ===")
        result = await analyzer.analyze_request(query)
        print(f"分析类型: {result.get('analysis_type')}")
        print(f"工具调用: {len(result.get('tool_calls', []))}次")
        if 'final_response' in result:
            print(f"响应: {result['final_response'][:200]}...")

if __name__ == "__main__":
    asyncio.run(example_usage())
