#!/bin/bash

# tldw 一键启动脚本
# 使用临时隧道模式（无需 Cloudflare 登录）

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLOUDFLARED="${PROJECT_DIR}/venv/lib/python3.12/site-packages/pycloudflared/cloudflared-linux-amd64"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 加载 .env 配置
if [ -f "${PROJECT_DIR}/.env" ]; then
    export $(grep -v '^#' "${PROJECT_DIR}/.env" | xargs)
    log_info "已加载 .env 配置"
fi

PORT="${PORT:-5123}"

# 激活虚拟环境
source "${PROJECT_DIR}/venv/bin/activate"
log_info "已激活虚拟环境"

# 检查 cloudflared
if [ ! -f "$CLOUDFLARED" ]; then
    log_error "cloudflared 未找到，请先运行: pip install pycloudflared"
    exit 1
fi

# 清理函数
cleanup() {
    log_info "正在关闭服务..."
    [ -n "$TUNNEL_PID" ] && kill $TUNNEL_PID 2>/dev/null || true
    [ -n "$FLASK_PID" ] && kill $FLASK_PID 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM

# 启动 Flask（后台）
log_info "启动 Flask 服务..."
cd "$PROJECT_DIR"
python app.py &
FLASK_PID=$!
sleep 2

# 检查 Flask 是否启动成功
if ! kill -0 $FLASK_PID 2>/dev/null; then
    log_error "Flask 启动失败"
    exit 1
fi
log_info "Flask 已启动 (PID: $FLASK_PID)"

# 启动临时隧道（无需登录）
log_info "启动 Cloudflared 临时隧道..."
$CLOUDFLARED tunnel --url http://localhost:${PORT} 2>&1 &
TUNNEL_PID=$!

# 等待隧道输出 URL
sleep 5

echo ""
echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  服务已启动！${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""
echo -e "📍 本地地址: ${GREEN}http://localhost:${PORT}${NC}"
echo -e "❤️  健康检查: ${GREEN}http://localhost:${PORT}/api/health${NC}"
echo ""
echo -e "${YELLOW}请查看上方 cloudflared 输出的 trycloudflare.com 地址${NC}"
echo -e "${YELLOW}然后在 https://ytquickbite.vercel.app/ 设置页面填入${NC}"
echo ""
echo "按 Ctrl+C 停止服务"
echo ""

# 等待
wait $FLASK_PID
