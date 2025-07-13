import os
import json
import asyncio
import google.generativeai as genai
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import logging
from typing import Dict, List, Any, Optional
from universal_travel_analyzer import UniversalTravelAnalyzer

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 加载 .env 文件中的环境变量
load_dotenv()

app = FastAPI(
    title="Universal Intelligent Travel Service",
    description="通用智能出行服务 - 使用LLM推理处理各种出行相关需求",
    version="1.0.0"
)

# Mount the static directory to serve frontend files
app.mount("/static", StaticFiles(directory="static"), name="static")

class TravelRequest(BaseModel):
    """通用出行请求模型"""
    query: str  # 用户的完整需求描述
    context: Dict[str, Any] = {}  # 可选的上下文信息
    preferences: str = ""  # 用户偏好
    constraints: Dict[str, Any] = {}  # 约束条件（如预算、时间等）

class ChatRequest(BaseModel):
    """对话式请求模型"""
    message: str  # 用户消息
    conversation_id: Optional[str] = None  # 会话ID，用于维持上下文
    session_data: Dict[str, Any] = {}  # 会话数据

@app.post("/analyze")
async def analyze_travel_request(request: TravelRequest):
    """
    通用智能出行分析接口
    支持各种出行相关需求：找房、旅游攻略、路线规划、美食推荐等
    """
    logger.info(f"Processing travel request: {request.query}")
    
    try:
        # 使用通用智能分析器
        analyzer = UniversalTravelAnalyzer()
        
        # 执行智能分析
        analysis_results = await analyzer.analyze_request(
            query=request.query,
            context=request.context,
            preferences=request.preferences,
            constraints=request.constraints
        )
        
        # 检查是否成功生成分析结果
        if "final_response" not in analysis_results:
            return {
                "error": "无法生成分析结果",
                "debug_info": analysis_results,
                "message": "LLM可能未能完成分析流程，请检查工具调用情况"
            }
        
        return {
            "success": True,
            "response": analysis_results["final_response"],
            "analysis_type": analysis_results.get("analysis_type", "unknown"),
            "tools_used": [call.get("tool_name") for call in analysis_results.get("tool_calls", [])],
            "metadata": {
                "query": request.query,
                "processing_time": analysis_results.get("processing_time", 0),
                "tool_calls_count": len(analysis_results.get("tool_calls", [])),
                "analysis_confidence": analysis_results.get("confidence_score", 0.8),
                "data_sources": list(analysis_results.get("data_sources", set()))
            },
            "raw_data": analysis_results
        }
        
    except Exception as e:
        logger.error(f"Travel analysis failed: {e}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")

@app.post("/chat")
async def chat_with_analyzer(request: ChatRequest):
    """
    对话式智能分析接口
    支持多轮对话，维持上下文状态
    """
    logger.info(f"Processing chat message: {request.message}")
    
    try:
        analyzer = UniversalTravelAnalyzer()
        
        # 如果有会话ID，尝试恢复会话状态
        if request.conversation_id:
            analyzer.load_conversation_state(request.conversation_id, request.session_data)
        
        # 处理对话消息
        chat_result = await analyzer.process_chat_message(
            message=request.message,
            conversation_id=request.conversation_id
        )
        
        return {
            "success": True,
            "response": chat_result["response"],
            "conversation_id": chat_result["conversation_id"],
            "session_data": chat_result.get("session_data", {}),
            "suggestions": chat_result.get("suggestions", []),
            "requires_action": chat_result.get("requires_action", False),
            "metadata": {
                "message_type": chat_result.get("message_type", "general"),
                "confidence": chat_result.get("confidence", 0.8),
                "tools_used": chat_result.get("tools_used", [])
            }
        }
        
    except Exception as e:
        logger.error(f"Chat processing failed: {e}")
        raise HTTPException(status_code=500, detail=f"Chat failed: {e}")

@app.get("/capabilities")
async def get_capabilities():
    """
    获取系统能力描述
    返回支持的分析类型和可用工具
    """
    try:
        analyzer = UniversalTravelAnalyzer()
        capabilities = await analyzer.get_system_capabilities()
        
        return {
            "supported_scenarios": capabilities.get("scenarios", []),
            "available_tools": capabilities.get("tools", []),
            "analysis_types": capabilities.get("analysis_types", []),
            "data_sources": capabilities.get("data_sources", []),
            "example_queries": capabilities.get("examples", [])
        }
        
    except Exception as e:
        logger.error(f"Failed to get capabilities: {e}")
        return {"error": f"Failed to get capabilities: {e}"}

@app.get("/examples")
async def get_usage_examples():
    """
    获取使用示例
    """
    examples = [
        {
            "category": "租房需求",
            "query": "我在北京海淀区和朝阳区都有工作，想找一个通勤方便的房子，预算5000-8000元",
            "expected_analysis": ["地理位置分析", "交通路线规划", "房源搜索", "成本分析"]
        },
        {
            "category": "旅游规划", 
            "query": "我想去成都玩3天，喜欢美食和历史文化，预算3000元，帮我规划一下行程",
            "expected_analysis": ["景点推荐", "美食攻略", "住宿建议", "行程规划", "预算分配"]
        },
        {
            "category": "路线规划",
            "query": "从上海到杭州最经济的出行方式是什么？包括时间和费用对比",
            "expected_analysis": ["交通方式对比", "费用计算", "时间分析", "路线推荐"]
        },
        {
            "category": "商务出行",
            "query": "下周要去深圳出差2天，需要住在会展中心附近，要求商务酒店，预算500元/晚",
            "expected_analysis": ["酒店搜索", "位置分析", "商务设施", "预订建议"]
        },
        {
            "category": "周边探索",
            "query": "我在广州天河区，想找周末可以去的好玩地方，不要太远，适合拍照",
            "expected_analysis": ["周边景点", "交通便利性", "特色分析", "摄影推荐"]
        }
    ]
    
    return {"usage_examples": examples}

@app.get("/debug/analyze-query/{query}")
async def debug_analyze_query(query: str):
    """
    调试接口：分析查询意图但不执行具体分析
    """
    try:
        analyzer = UniversalTravelAnalyzer()
        intent_analysis = await analyzer.analyze_query_intent(query)
        
        return {
            "query": query,
            "intent_analysis": intent_analysis,
            "suggested_tools": intent_analysis.get("recommended_tools", []),
            "analysis_plan": intent_analysis.get("analysis_plan", []),
            "confidence": intent_analysis.get("confidence", 0.0)
        }
        
    except Exception as e:
        logger.error(f"Query analysis failed: {e}")
        return {"error": f"Query analysis failed: {e}"}

@app.get("/debug/tools")
async def debug_available_tools():
    """
    调试接口：获取所有可用的工具
    """
    try:
        analyzer = UniversalTravelAnalyzer()
        tools_info = await analyzer.get_available_tools()
        return {"available_tools": tools_info}
    except Exception as e:
        logger.error(f"Failed to get tools: {e}")
        return {"error": f"Failed to get tools: {e}"}

@app.get("/health")
async def health_check():
    """
    健康检查接口
    """
    try:
        # 简单检查LLM连接
        analyzer = UniversalTravelAnalyzer()
        health_status = await analyzer.health_check()
        
        return {
            "status": "healthy" if health_status["llm_available"] else "degraded",
            "components": health_status,
            "timestamp": health_status.get("timestamp")
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": asyncio.get_event_loop().time()
        }

@app.get("/", response_class=FileResponse)
async def read_index():
    """Serves the frontend's index.html file."""
    return "static/travel_index.html"

if __name__ == "__main__":
    import uvicorn
    import argparse

    parser = argparse.ArgumentParser(description="Run the Universal Intelligent Travel Service.")
    parser.add_argument("--port", type=int, default=8002, help="Port to run the server on.")
    args = parser.parse_args()

    uvicorn.run(app, host="0.0.0.0", port=args.port)
