#!/bin/bash

# tldw 一键启动脚本

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "🚀 启动 tldw 服务..."

# 加载 .env
if [ -f "${PROJECT_DIR}/.env" ]; then
    export $(grep -v '^#' "${PROJECT_DIR}/.env" | xargs)
fi

PORT="${PORT:-5123}"

# 激活虚拟环境
source "${PROJECT_DIR}/venv/bin/activate"

cd "$PROJECT_DIR"

# 先后台启动 Flask
echo "📦 启动 Flask..."
python app.py &
FLASK_PID=$!

# 等待 Flask 启动
sleep 3

# 检查 Flask 是否成功
if ! kill -0 $FLASK_PID 2>/dev/null; then
    echo "❌ Flask 启动失败"
    exit 1
fi

echo "✅ Flask 已启动 (PID: $FLASK_PID)"

# 启动隧道
echo "🌐 启动隧道..."

# 捕获 Ctrl+C 信号，清理所有进程
cleanup() {
    echo ""
    echo "🛑 停止服务..."
    kill $FLASK_PID 2>/dev/null
    exit 0
}
trap cleanup SIGINT SIGTERM

# 启动隧道（前台运行）
python tunnel.py

# 清理 Flask
kill $FLASK_PID 2>/dev/null
