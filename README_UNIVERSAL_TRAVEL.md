# 🚀 通用智能出行服务 (Universal Intelligent Travel Service)

基于LLM推理的智能出行助手，支持租房、旅游、路线规划等多种出行相关场景。

## 🎯 项目概述

这是一个通用的智能出行服务系统，通过以下方式实现：

1. **LLM推理引擎**: 使用Google Gemini分析用户意图，智能制定分析计划
2. **动态工具调用**: 根据需求自动选择和调用高德地图MCP工具
3. **场景识别**: 自动识别不同类型的出行需求
4. **多轮对话**: 支持上下文对话，逐步完善需求

## 🏗️ 系统架构

### 核心组件

```
用户请求 → 意图分析 → 场景识别 → 工具选择 → 数据收集 → 智能分析 → 结果生成
```

### 架构对比

| 组件 | 原始租房系统 | 通用出行系统 |
|------|-------------|-------------|
| **分析器** | `IntelligentRentalAnalyzer` | `UniversalTravelAnalyzer` |
| **服务接口** | `intelligent_house_service.py` | `universal_travel_service.py` |
| **场景支持** | 仅租房分析 | 5+种出行场景 |
| **工具调用** | 固定流程 | 动态智能选择 |
| **用户交互** | 单次分析 | 支持多轮对话 |

## 🎨 支持的场景

### 1. 租房位置分析 (rental_housing)
- **关键词**: 租房、找房、住房、房子、租赁、居住
- **分析内容**: 通勤路线、周边设施、生活便利性
- **示例**: "我在北京海淀区和朝阳区都有工作，想找一个通勤方便的房子"

### 2. 旅游行程规划 (travel_planning)
- **关键词**: 旅游、旅行、攻略、景点、行程、度假
- **分析内容**: 景点推荐、路线规划、预算分配
- **示例**: "帮我规划成都3天2夜旅游攻略，喜欢美食和历史文化"

### 3. 路线规划 (route_planning)
- **关键词**: 路线、导航、出行方式、交通、到达
- **分析内容**: 交通方式对比、时间成本、费用分析
- **示例**: "从上海到杭州最经济的出行方式是什么？"

### 4. 地点搜索 (poi_search)
- **关键词**: 附近、周边、找、搜索、推荐
- **分析内容**: 周边设施、特色分析、推荐排序
- **示例**: "我在广州天河区，想找周末可以去的好玩地方"

### 5. 住宿推荐 (accommodation)
- **关键词**: 酒店、住宿、客栈、民宿、宾馆
- **分析内容**: 住宿选择、位置分析、性价比评估
- **示例**: "深圳会展中心附近有什么好的商务酒店？"

## 🔧 技术实现

### 智能分析流程

```python
# 1. 意图分析
intent_analysis = await analyzer.analyze_query_intent(query)

# 2. 场景匹配
scenario = match_scenario(intent_analysis)

# 3. 动态工具调用
while not analysis_complete:
    llm_decision = await get_next_action(current_state)
    if llm_decision == "CALL_TOOL":
        result = await tool_manager.call_tool(tool_name, args)
        update_analysis_data(result)
    elif llm_decision == "GENERATE_FINAL_RESPONSE":
        break

# 4. 结果生成
final_response = await generate_response(collected_data)
```

### 关键特性

#### 1. 智能意图识别
```python
def analyze_query_intent(self, query: str) -> Dict[str, Any]:
    """
    使用LLM分析用户查询意图，返回：
    - analysis_type: 分析类型
    - confidence: 置信度
    - key_entities: 关键实体
    - location_info: 地点信息
    - recommended_tools: 建议工具
    """
```

#### 2. 动态工具选择
- 根据LLM推理动态选择工具
- 支持工具调用链的智能优化
- 错误处理和重试机制

#### 3. 多轮对话支持
```python
class ConversationManager:
    """
    对话管理器，支持：
    - 会话状态维护
    - 上下文理解
    - 多轮交互
    """
```

## 📱 API接口

### 1. 智能分析接口
```bash
POST /analyze
Content-Type: application/json

{
    "query": "用户需求描述",
    "preferences": "用户偏好（可选）",
    "constraints": {"budget": "预算约束"}
}
```

### 2. 对话接口
```bash
POST /chat
Content-Type: application/json

{
    "message": "用户消息",
    "conversation_id": "会话ID（可选）"
}
```

### 3. 系统能力查询
```bash
GET /capabilities
```

### 4. 调试接口
```bash
GET /debug/analyze-query/{query}  # 分析查询意图
GET /debug/tools                 # 获取可用工具
GET /health                      # 健康检查
```

## 🚀 快速开始

### 1. 环境配置
```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
export GOOGLE_API_KEY="your_gemini_api_key"
export AMAP_MCP_KEY="your_amap_key"
```

### 2. 启动服务
```bash
# 启动通用出行服务
python universal_travel_service.py --port 8002

# 访问前端界面
open http://localhost:8002
```

### 3. 使用示例

#### Python客户端
```python
import requests

# 智能分析
response = requests.post('http://localhost:8002/analyze', json={
    "query": "我在北京海淀区工作，想找房子",
    "preferences": "靠近地铁",
    "constraints": {"budget": "5000-8000元"}
})

result = response.json()
print(result['response'])
```

#### 对话模式
```python
# 开始对话
response = requests.post('http://localhost:8002/chat', json={
    "message": "你好，我想找房子"
})

conversation_id = response.json()['conversation_id']

# 继续对话
response = requests.post('http://localhost:8002/chat', json={
    "message": "我在海淀区工作",
    "conversation_id": conversation_id
})
```

## 📊 系统对比

### 与原始租房系统的差异

| 特性 | 原始系统 | 通用系统 |
|------|---------|---------|
| **适用场景** | 仅租房分析 | 5+种出行场景 |
| **分析方式** | 固定步骤 | LLM动态推理 |
| **工具调用** | 预定义流程 | 智能选择 |
| **交互方式** | 单次请求 | 多轮对话 |
| **扩展性** | 场景固定 | 易于扩展新场景 |
| **智能化** | 中等 | 高度智能化 |

### 技术优势

1. **通用性**: 一套系统支持多种出行场景
2. **智能化**: LLM推理驱动的分析流程
3. **可扩展**: 易于添加新场景和工具
4. **用户友好**: 自然语言交互，支持对话
5. **灵活性**: 动态工具选择，适应不同需求

## 🔮 扩展方向

### 1. 新增场景
- 商务出行规划
- 学校选择分析
- 医疗资源搜索
- 美食探索推荐

### 2. 工具集成
- 更多地图服务商（百度、腾讯）
- 房产数据API
- 天气服务
- 交通实时数据

### 3. 功能增强
- 语音交互支持
- 图像识别能力
- 个性化推荐算法
- 历史偏好学习

## 📁 文件结构

```
.
├── universal_travel_service.py      # 主服务文件
├── universal_travel_analyzer.py     # 核心分析器
├── intelligent_house_service.py     # 原始租房服务（对比参考）
├── intelligent_rental_analyzer.py   # 原始租房分析器（对比参考）
├── static/
│   ├── travel_index.html           # 通用出行前端界面
│   └── index.html                   # 原始租房前端界面
├── requirements.txt                 # 项目依赖
└── README_UNIVERSAL_TRAVEL.md       # 本说明文档
```

## 💡 设计理念

这个通用智能出行服务的设计理念是：

1. **以用户为中心**: 自然语言描述需求，无需学习复杂界面
2. **智能化驱动**: LLM推理决策，而非固定规则
3. **场景无关**: 一套架构支持多种出行场景
4. **持续学习**: 通过对话逐步完善需求理解
5. **开放扩展**: 易于集成新的数据源和分析能力

通过这种设计，我们创建了一个真正"智能"的出行服务系统，能够理解用户意图、动态选择合适的分析方法，并提供个性化的建议。

## 🤝 贡献

欢迎提交Issue和Pull Request来帮助改进这个项目！

## 📄 许可证

MIT License
