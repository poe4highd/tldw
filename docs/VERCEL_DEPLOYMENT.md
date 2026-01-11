# Vercel + 本地处理部署指南

本文档说明如何将 tldw 项目部署到 Vercel，同时保持视频处理在本地服务器运行。

## 架构概览

```
┌─────────────────────┐              ┌─────────────────────┐
│      Vercel         │              │     本地服务器       │
│    (前端/代理)       │    HTTPS     │    (Flask API)      │
│                     │ ───────────→ │                     │
│  - 静态页面托管      │              │  - 视频下载 (yt-dlp) │
│  - API 请求转发      │  cloudflared │  - 语音转写 (Whisper)│
│  - CDN 加速         │    tunnel    │  - AI 总结 (OpenAI)  │
└─────────────────────┘              │  - SQLite 数据库     │
         ↑                           └─────────────────────┘
         │                                     ↑
      用户访问                              GPU 加速
   your-app.vercel.app
```

## 前置要求

- 本地服务器（Linux/macOS/Windows）
- Python 3.10+（用于后端）
- Cloudflare 账号（免费）
- Vercel 账号（免费）
- Node.js 18+（用于前端构建）

---

## 第一部分：本地后端配置

### 1.1 环境准备

按照 [README.md](../README.md#2-创建虚拟环境) 完成基础环境设置即可。

> `flask-cors` 和 `pycloudflared` 已包含在 `requirements.txt` 中，无需额外安装。

### 1.2 修改 app.py 添加 CORS

在 `app.py` 文件顶部添加：

```python
from flask_cors import CORS

app = Flask(__name__)

# CORS 配置 - 允许 Vercel 域名访问
CORS(app,
     origins=[
         "https://your-app.vercel.app",  # 替换为你的 Vercel 域名
         "https://*.vercel.app",          # Vercel 预览部署
         "http://localhost:3000"          # 本地开发
     ],
     supports_credentials=True,
     methods=["GET", "POST", "OPTIONS"],
     allow_headers=["Content-Type", "Authorization"]
)
```

### 1.3 添加健康检查端点

在 `app.py` 中添加：

```python
@app.route('/api/health')
def health_check():
    """健康检查端点，用于 Vercel 验证后端状态"""
    return jsonify({
        'status': 'ok',
        'service': 'tldw-backend',
        'gpu_available': torch.cuda.is_available() if 'torch' in dir() else False
    })
```

### 1.4 统一 API 路由前缀

建议将所有 API 路由添加 `/api` 前缀，便于 Vercel 代理配置：

```python
# 原来
@app.route('/submit', methods=['POST'])

# 改为
@app.route('/api/submit', methods=['POST'])
```

---

## 第二部分：Cloudflared 隧道配置

Cloudflared 提供免费的安全隧道，将本地服务暴露到公网。

### 2.1 验证 Cloudflared

cloudflared 已通过 pip 安装（pycloudflared 包），激活 venv 后直接可用：

```bash
# 验证安装
cloudflared --version
```

### 2.2 登录 Cloudflare

```bash
cloudflared tunnel login
```

这会打开浏览器，选择你要使用的域名（或使用 Cloudflare 提供的免费子域名）。

### 2.3 创建隧道

```bash
# 创建隧道
cloudflared tunnel create tldw-backend

# 记录输出的隧道 ID，类似：
# Created tunnel tldw-backend with id xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

### 2.4 配置隧道

创建配置文件 `~/.cloudflared/config.yml`：

```yaml
# Cloudflared 隧道配置
tunnel: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx  # 替换为你的隧道 ID
credentials-file: /home/你的用户名/.cloudflared/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.json

ingress:
  # 将流量转发到本地 Flask 服务
  - hostname: tldw-api.你的域名.com  # 替换为你的域名
    service: http://localhost:5123
    originRequest:
      noTLSVerify: true

  # 默认规则（必须有）
  - service: http_status:404
```

**如果没有自己的域名**，可以使用 Cloudflare 免费的 `trycloudflare.com` 子域名：

```bash
# 快速启动（无需配置文件，但 URL 每次启动会变）
cloudflared tunnel --url http://localhost:5123
```

### 2.5 配置 DNS（如果使用自己的域名）

```bash
# 将域名指向隧道
cloudflared tunnel route dns tldw-backend tldw-api.你的域名.com
```

### 2.6 启动隧道

```bash
# 在 venv 激活状态下运行
cloudflared tunnel run tldw-backend
```

> **提示**：隧道需要保持运行，可以使用 `&` 后台运行或配合启动脚本使用。

### 2.7 验证隧道

```bash
# 检查隧道状态
curl https://tldw-api.你的域名.com/api/health

# 应该返回：
# {"status": "ok", "service": "tldw-backend", "gpu_available": true}
```

---

## 第三部分：Vercel 前端配置

### 3.1 项目结构调整

创建前端目录结构：

```
tldw/
├── app.py                 # Flask 后端（本地运行）
├── frontend/              # Vercel 部署的前端
│   ├── public/
│   │   └── favicon.ico
│   ├── src/
│   │   ├── pages/
│   │   │   └── index.html
│   │   └── js/
│   │       └── app.js
│   ├── vercel.json
│   └── package.json
└── ...
```

### 3.2 创建 vercel.json

在 `frontend/vercel.json`：

```json
{
  "version": 2,
  "name": "tldw-frontend",
  "builds": [
    {
      "src": "public/**",
      "use": "@vercel/static"
    }
  ],
  "routes": [
    {
      "src": "/api/(.*)",
      "dest": "https://tldw-api.你的域名.com/api/$1",
      "headers": {
        "Access-Control-Allow-Origin": "*"
      }
    },
    {
      "src": "/(.*)",
      "dest": "/public/$1"
    }
  ],
  "env": {
    "API_BASE_URL": "https://tldw-api.你的域名.com"
  }
}
```

### 3.3 前端 API 调用示例

```javascript
// frontend/src/js/app.js

const API_BASE = ''; // 使用相对路径，让 Vercel 代理转发

async function submitVideo(youtubeUrl) {
    const response = await fetch('/api/submit', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: `youtube_url=${encodeURIComponent(youtubeUrl)}`
    });

    if (!response.ok) {
        throw new Error('提交失败');
    }

    return response.json();
}

async function checkHealth() {
    try {
        const response = await fetch('/api/health');
        const data = await response.json();
        console.log('后端状态:', data);
        return data.status === 'ok';
    } catch (error) {
        console.error('后端不可用:', error);
        return false;
    }
}
```

### 3.4 部署到 Vercel

**方式一：CLI 部署**
```bash
cd frontend

# 安装 Vercel CLI
npm i -g vercel

# 登录
vercel login

# 部署
vercel --prod
```

**方式二：Git 集成**
1. 将代码推送到 GitHub
2. 在 Vercel Dashboard 导入项目
3. 设置根目录为 `frontend`
4. 自动部署

---

## 第四部分：完整启动流程

### 4.1 启动本地后端

```bash
# 终端 1：启动 Flask
cd /home/xs/projects/tldw
source venv/bin/activate
python app.py

# 终端 2：启动 Cloudflared 隧道
source venv/bin/activate
cloudflared tunnel run tldw-backend
```

### 4.2 创建启动脚本

创建 `start-backend.sh`：

```bash
#!/bin/bash

# tldw 后端启动脚本

PROJECT_DIR="/home/xs/projects/tldw"

echo "🚀 启动 tldw 后端服务..."

# 激活虚拟环境
source ${PROJECT_DIR}/venv/bin/activate

# 后台启动 cloudflared 隧道
echo "🌐 启动 Cloudflared 隧道..."
cloudflared tunnel run tldw-backend &
TUNNEL_PID=$!
echo "✅ Cloudflared 隧道已启动 (PID: $TUNNEL_PID)"

# 启动 Flask
echo "🌐 启动 Flask 服务 (端口 5123)..."
cd ${PROJECT_DIR}
python app.py

# Flask 退出时关闭隧道
kill $TUNNEL_PID 2>/dev/null
```

添加执行权限：
```bash
chmod +x start-backend.sh
```

---

## 第五部分：故障排查

### 5.1 常见问题

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| CORS 错误 | 域名未加入白名单 | 检查 Flask CORS 配置 |
| 502 Bad Gateway | Flask 未启动 | 检查本地服务状态 |
| 隧道断开 | cloudflared 进程退出 | 使用启动脚本管理 |
| API 超时 | 视频处理时间长 | 增加 Vercel timeout |

### 5.2 调试命令

```bash
# 检查 Flask 是否运行
curl http://localhost:5123/api/health

# 检查隧道状态
cloudflared tunnel info tldw-backend

# 测试外部访问
curl https://tldw-api.你的域名.com/api/health
```

### 5.3 Vercel 日志

```bash
# 查看部署日志
vercel logs your-app.vercel.app

# 查看函数日志（如果使用 serverless functions）
vercel logs your-app.vercel.app --follow
```

---

## 安全建议

1. **API 鉴权**：添加 API Key 验证，防止滥用
2. **速率限制**：使用 Flask-Limiter 限制请求频率
3. **HTTPS**：Cloudflared 默认提供 HTTPS，确保始终使用
4. **环境变量**：敏感信息（OpenAI Key 等）存储在环境变量中
5. **IP 白名单**：可在 Cloudflare Dashboard 配置访问规则

```python
# 示例：简单的 API Key 验证
from functools import wraps

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if api_key != os.environ.get('API_KEY'):
            return jsonify({'error': 'Invalid API key'}), 401
        return f(*args, **kwargs)
    return decorated

@app.route('/api/submit', methods=['POST'])
@require_api_key
def submit_url():
    # ...
```

---

## 快速参考

| 组件 | 地址 | 说明 |
|------|------|------|
| 本地 Flask | `http://localhost:5123` | 后端 API |
| Cloudflared 隧道 | `https://tldw-api.你的域名.com` | 公网访问地址 |
| Vercel 前端 | `https://your-app.vercel.app` | 用户访问入口 |
| Cloudflare Dashboard | `https://dash.cloudflare.com` | 隧道管理 |
| Vercel Dashboard | `https://vercel.com/dashboard` | 前端管理 |
