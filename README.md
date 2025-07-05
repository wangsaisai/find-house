# 租房位置智能分析器 (Optimal Rental Location Finder)

**在线体验地址**: [http://34.176.0.152:8084/](http://34.176.0.152:8084/)

这是一个基于 FastAPI 和 Google Gemini 的智能租房位置分析工具。它可以根据用户提供的两个工作或学习地址，结合高德地图服务，智能分析并推荐最合适的租房区域。前端界面友好，后端处理逻辑强大，旨在帮助用户在通勤便利性、生活成本和生活质量之间找到最佳平衡。


![应用截图](house.png)

## ✨ 主要功能

- **双地址通勤分析**：输入两个通勤点，系统将分析两点之间的交通状况。
- **智能区域推荐**：基于地理位置中点、交通便利性和周边设施，推荐3个最合适的租房区域。
- **详细通勤报告**：为每个推荐区域提供到两个工作地的详细通勤方案，包括步行、地铁/公交线路、换乘信息、预估时间和费用。
- **生活设施概览**：展示推荐区域周边的购物、餐饮、医疗、娱乐等生活配套设施。
- **成本与实用建议**：提供租金预估、区域对比、选房要点、看房清单等全方位的租房建议。
- **前后端一体化**：使用 FastAPI 同时提供后端 API 和前端静态文件，简化部署流程。

## 🛠️ 技术栈

- **后端**:
  - [FastAPI](https://fastapi.tiangolo.com/): 高性能的 Python Web 框架。
  - [Google Gemini](https://ai.google.dev/): 用于生成智能分析和推荐报告。
  - [Aiohttp](https://docs.aiohttp.org/): 用于异步调用高德地图 MCP 服务。
  - [Uvicorn](https://www.uvicorn.org/): ASGI 服务器。
- **前端**:
  - HTML5
  - CSS3
  - JavaScript
  - [Marked.js](https://marked.js.org/): 用于在前端渲染 Markdown 格式的分析报告。
- **服务**:
  - [高德地图 MCP](https://lbs.amap.com/): 提供地理编码、路线规划、周边搜索等地图服务。

## 🚀 安装与设置

1.  **克隆仓库**
    ```bash
    git clone <your-repo-url>
    cd <your-repo-directory>
    ```

2.  **创建并激活虚拟环境** (推荐)
    ```bash
    python -m venv venv
    # Windows
    venv\Scripts\activate
    # macOS/Linux
    source venv/bin/activate
    ```

3.  **安装依赖**
    ```bash
    pip install -r requirements.txt
    ```
    *注意: `requirements.txt` 文件需要您手动创建，内容如下：*
    ```
    fastapi
    uvicorn
    python-dotenv
    google-generativeai
    aiohttp
    ```

4.  **配置环境变量**
    在项目根目录下创建一个 `.env` 文件，并填入您的 API 密钥：
    ```env
    GOOGLE_API_KEY="YOUR_GOOGLE_API_KEY"
    AMAP_MCP_KEY="YOUR_AMAP_MCP_KEY"
    ```
    - `GOOGLE_API_KEY`: 您的 Google Gemini API 密钥。
    - `AMAP_MCP_KEY`: 您的高德地图 Web 服务 API 密钥。

## ▶️ 运行应用

在项目根目录下运行以下命令以启动服务：

```bash
# 使用默认端口 8000
python house.py

# 或者指定一个自定义端口，例如 9000
python house.py --port 9000
```

服务启动后，在您的浏览器中打开 `http://127.0.0.1:PORT` (其中 `PORT` 是您指定的端口号，默认为 `8000`) 即可访问应用。

## 📝 使用方法

1.  打开应用主页。
2.  输入两个工作/学习地址（已提供默认值）。
3.  （可选）输入您的预算范围和其它偏好。
4.  点击“开始分析”按钮。
5.  等待约1-2分钟，系统将生成并展示详细的租房分析报告。
