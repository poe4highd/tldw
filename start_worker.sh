#!/bin/bash

# YTQuickBite Worker 启动脚本
# 新架构：只需启动 worker，通过 Supabase 通信

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "🚀 YTQuickBite Worker"
echo "===================="

# 加载 .env
if [ -f "${PROJECT_DIR}/.env" ]; then
    set -a
    source "${PROJECT_DIR}/.env"
    set +a
    echo "✅ 已加载 .env"
else
    echo "❌ 未找到 .env 文件"
    exit 1
fi

# 检查必需的环境变量
if [ -z "$SUPABASE_URL" ]; then
    echo "❌ 缺少 SUPABASE_URL"
    exit 1
fi

if [ -z "$SUPABASE_SECRET_KEY" ] && [ -z "$SUPABASE_SERVICE_KEY" ]; then
    echo "❌ 缺少 SUPABASE_SECRET_KEY"
    exit 1
fi

# 激活虚拟环境（如果存在）
if [ -f "${PROJECT_DIR}/venv/bin/activate" ]; then
    source "${PROJECT_DIR}/venv/bin/activate"
    echo "✅ 已激活虚拟环境"
fi

cd "$PROJECT_DIR"

echo ""
echo "📡 连接 Supabase: $SUPABASE_URL"
echo "⏳ 启动 Worker..."
echo ""

# 启动 worker
python worker.py
