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
from intelligent_rental_analyzer import IntelligentRentalAnalyzer

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 加载 .env 文件中的环境变量
load_dotenv()

app = FastAPI(
    title="Intelligent Rental Location Finder",
    description="An API using LLM reasoning to intelligently find the best rental location with MCP tools.",
    version="2.0.0"
)

# Mount the static directory to serve frontend files
app.mount("/static", StaticFiles(directory="static"), name="static")

class RentalLocationRequest(BaseModel):
    work_address1: str  # 第一个工作/学习地点
    work_address2: str  # 第二个工作/学习地点
    budget_range: str = "不限"  # 预算范围，可选
    preferences: str = ""  # 其他偏好，如：靠近地铁、环境安静等

@app.post("/find_rental_location")
async def find_rental_location(request: RentalLocationRequest):
    """
    使用智能LLM推理和MCP服务找到最佳租房位置
    """
    logger.info(f"Processing rental location request for work addresses: {request.work_address1}, {request.work_address2}")
    
    try:
        # 使用智能租房位置分析器
        analyzer = IntelligentRentalAnalyzer()
        
        # 执行智能分析
        analysis_results = await analyzer.analyze_rental_locations(
            work_address1=request.work_address1,
            work_address2=request.work_address2,
            budget_range=request.budget_range,
            preferences=request.preferences
        )
        
        # 检查是否成功生成最终分析
        if "final_analysis" not in analysis_results:
            return {
                "error": "无法生成最终分析报告",
                "debug_info": analysis_results,
                "message": "LLM可能未能完成分析流程，请检查工具调用情况"
            }
        
        # 保持与原始接口一致的返回格式
        coordinates = analysis_results.get("coordinates", {})
        
        return {
            "rental_location_analysis": analysis_results["final_analysis"],
            "analysis_data": {
                "detected_city": coordinates.get("city1") or coordinates.get("city2"),
                "work_coordinates": {
                    "work_address1": f"{request.work_address1} -> {coordinates.get('work_location1', 'unknown')}",
                    "work_address2": f"{request.work_address2} -> {coordinates.get('work_location2', 'unknown')}",
                    "midpoint": "calculated by intelligent analyzer"
                },
                "user_preferences": {
                    "budget_range": request.budget_range,
                    "preferences": request.preferences
                },
                "analysis_summary": {
                    "intelligent_analysis": True,
                    "tool_calls_executed": len(analysis_results.get("tool_calls", [])),
                    "llm_guided_process": True,
                    "coordinates_found": len(coordinates) > 0,
                    "data_types_collected": list(analysis_results.get("analysis_data", {}).keys())
                }
            },
            "raw_mcp_data": analysis_results
        }
        
    except Exception as e:
        logger.error(f"Intelligent analysis failed: {e}")
        raise HTTPException(status_code=500, detail=f"Intelligent analysis failed: {e}")

@app.get("/compare_analyzers/{work_address1}/{work_address2}")
async def compare_analyzers(work_address1: str, work_address2: str, budget_range: str = "不限", preferences: str = ""):
    """
    比较原始分析器和智能分析器的结果
    """
    try:
        # 使用智能分析器
        intelligent_analyzer = IntelligentRentalAnalyzer()
        intelligent_results = await intelligent_analyzer.analyze_rental_locations(
            work_address1=work_address1,
            work_address2=work_address2,
            budget_range=budget_range,
            preferences=preferences
        )
        
        # 导入原始分析器进行比较
        from house import RentalLocationAnalyzer
        original_analyzer = RentalLocationAnalyzer()
        original_results, coord1, coord2, city = await original_analyzer.analyze_rental_locations(
            work_address1, work_address2
        )
        
        return {
            "comparison": {
                "intelligent_analyzer": {
                    "description": "使用LLM推理智能调用MCP工具",
                    "tool_calls_count": len(intelligent_results.get("tool_calls", [])),
                    "has_final_analysis": "final_analysis" in intelligent_results,
                    "coordinates_found": len(intelligent_results.get("coordinates", {})),
                    "data_categories": list(intelligent_results.get("analysis_data", {}).keys())
                },
                "original_analyzer": {
                    "description": "按固定步骤调用MCP工具",
                    "coordinates_found": bool(coord1 and coord2),
                    "detected_city": city,
                    "data_categories": list(original_results.keys())
                }
            },
            "intelligent_results": intelligent_results,
            "original_results": {
                "raw_data": original_results,
                "coordinates": {"coord1": coord1, "coord2": coord2},
                "city": city
            }
        }
        
    except Exception as e:
        logger.error(f"Analyzer comparison failed: {e}")
        raise HTTPException(status_code=500, detail=f"Analyzer comparison failed: {e}")

# 调试端点 - 保持与原始house.py一致的接口
@app.get("/debug/available-tools")
async def debug_available_tools():
    """调试：获取MCP服务器上可用的工具"""
    try:
        from intelligent_rental_analyzer import MCPToolManager, AMAP_MCP_URL
        async with MCPToolManager(AMAP_MCP_URL) as tool_manager:
            return {
                "available_tools": tool_manager.available_tools,
                "tools_description": tool_manager.get_tools_description()
            }
    except Exception as e:
        logger.error(f"Failed to get available tools: {e}")
        return {"error": f"Failed to get available tools: {e}"}

@app.get("/debug/test-geocode/{address}")
async def debug_test_geocode(address: str):
    """调试：测试地理编码功能"""
    try:
        from intelligent_rental_analyzer import MCPToolManager, AMAP_MCP_URL
        analyzer = IntelligentRentalAnalyzer()
        async with MCPToolManager(AMAP_MCP_URL) as tool_manager:
            result = await tool_manager.call_tool("maps_geo", {"address": address})
            coords, city = analyzer._extract_coordinates_and_city(result)
            return {
                "address": address,
                "geocode_result": result,
                "extracted_coordinates": coords,
                "detected_city": city
            }
    except Exception as e:
        logger.error(f"Geocode test failed: {e}")
        return {"error": f"Geocode test failed: {e}"}

@app.get("/debug/test-rental-analysis/{work_address1}/{work_address2}")
async def debug_test_rental_analysis(work_address1: str, work_address2: str):
    """调试：测试完整的租房分析计划"""
    try:
        analyzer = IntelligentRentalAnalyzer()
        results = await analyzer.analyze_rental_locations(work_address1, work_address2)
        coordinates = results.get("coordinates", {})
        
        return {
            "detected_city": coordinates.get("city1") or coordinates.get("city2"),
            "coordinates": {
                "work_location1": coordinates.get("work_location1"),
                "work_location2": coordinates.get("work_location2")
            },
            "analysis_results": results
        }
    except Exception as e:
        logger.error(f"Rental analysis test failed: {e}")
        return {"error": f"Rental analysis test failed: {e}"}

@app.get("/debug/intelligent-analysis-steps/{work_address1}/{work_address2}")
async def debug_intelligent_analysis_steps(work_address1: str, work_address2: str):
    """调试：查看智能分析器的详细执行步骤"""
    try:
        analyzer = IntelligentRentalAnalyzer()
        results = await analyzer.analyze_rental_locations(work_address1, work_address2)
        
        # 提取详细的步骤信息
        steps_info = []
        for i, call in enumerate(results.get("tool_calls", []), 1):
            step_info = {
                "step": i,
                "iteration": call.get("iteration", i),
                "tool_name": call.get("tool_name", "unknown"),
                "arguments": call.get("arguments", {}),
                "reason": call.get("reason", "未说明"),
                "success": "error" not in call,
                "error": call.get("error")
            }
            steps_info.append(step_info)
        
        return {
            "analysis_steps": steps_info,
            "summary": {
                "total_steps": len(steps_info),
                "successful_calls": len([s for s in steps_info if s["success"]]),
                "failed_calls": len([s for s in steps_info if not s["success"]]),
                "unique_tools_used": len(set([s["tool_name"] for s in steps_info])),
                "has_final_analysis": "final_analysis" in results
            },
            "conversation_history": results.get("conversation_history", []),
            "full_results": results
        }
        
    except Exception as e:
        logger.error(f"Debug analysis failed: {e}")
        raise HTTPException(status_code=500, detail=f"Debug analysis failed: {e}")

@app.get("/", response_class=FileResponse)
async def read_index():
    """Serves the frontend's index.html file."""
    return "static/index.html"

if __name__ == "__main__":
    import uvicorn
    import argparse

    parser = argparse.ArgumentParser(description="Run the Intelligent Rental Location Finder API.")
    parser.add_argument("--port", type=int, default=8001, help="Port to run the server on.")
    args = parser.parse_args()

    uvicorn.run(app, host="0.0.0.0", port=args.port)
