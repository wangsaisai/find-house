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

@app.post("/intelligent_find_rental_location")
async def intelligent_find_rental_location(request: RentalLocationRequest):
    """
    使用智能LLM推理和MCP服务找到最佳租房位置
    """
    logger.info(f"Processing intelligent rental location request for work addresses: {request.work_address1}, {request.work_address2}")
    
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
        
        return {
            "status": "success",
            "intelligent_analysis": analysis_results["final_analysis"],
            "analysis_metadata": {
                "user_request": {
                    "work_address1": request.work_address1,
                    "work_address2": request.work_address2,
                    "budget_range": request.budget_range,
                    "preferences": request.preferences
                },
                "llm_process": {
                    "tool_calls_count": len(analysis_results.get("tool_calls", [])),
                    "coordinates_found": len(analysis_results.get("coordinates", {})),
                    "data_types_collected": list(analysis_results.get("analysis_data", {}).keys())
                }
            },
            "raw_analysis_data": analysis_results
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

@app.get("/debug/intelligent-analysis-steps/{work_address1}/{work_address2}")
async def debug_intelligent_analysis_steps(work_address1: str, work_address2: str):
    """
    调试：查看智能分析器的详细执行步骤
    """
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
