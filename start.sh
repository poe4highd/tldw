#!/bin/bash

# tldw 一键启动脚本
# 自动配置 cloudflared 隧道并启动 Flask

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLOUDFLARED="${PROJECT_DIR}/venv/lib/python3.12/site-packages/pycloudflared/cloudflared-linux-amd64"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 加载 .env 配置
if [ -f "${PROJECT_DIR}/.env" ]; then
    export $(grep -v '^#' "${PROJECT_DIR}/.env" | xargs)
    log_info "已加载 .env 配置"
else
    log_error ".env 文件不存在"
    exit 1
fi

# 默认值
TUNNEL_NAME="${TUNNEL_NAME:-tldw-backend}"
PORT="${PORT:-5123}"

# 激活虚拟环境
source "${PROJECT_DIR}/venv/bin/activate"
log_info "已激活虚拟环境"

# 检查 cloudflared
if [ ! -f "$CLOUDFLARED" ]; then
    log_error "cloudflared 未找到，请先运行: pip install pycloudflared"
    exit 1
fi

# 检查隧道是否存在
tunnel_exists() {
    $CLOUDFLARED tunnel list 2>/dev/null | grep -q "$TUNNEL_NAME"
}

# 创建隧道（如果不存在）
if ! tunnel_exists; then
    log_info "创建隧道: $TUNNEL_NAME"
    $CLOUDFLARED tunnel create "$TUNNEL_NAME"

    # 获取隧道 ID
    TUNNEL_ID=$($CLOUDFLARED tunnel list | grep "$TUNNEL_NAME" | awk '{print $1}')
    log_info "隧道 ID: $TUNNEL_ID"

    # 如果配置了域名，设置 DNS
    if [ -n "$TUNNEL_HOSTNAME" ]; then
        log_info "配置 DNS: $TUNNEL_HOSTNAME"
        $CLOUDFLARED tunnel route dns "$TUNNEL_NAME" "$TUNNEL_HOSTNAME" || true
    fi
else
    log_info "隧道已存在: $TUNNEL_NAME"
    TUNNEL_ID=$($CLOUDFLARED tunnel list | grep "$TUNNEL_NAME" | awk '{print $1}')
fi

# 生成配置文件
CONFIG_DIR="$HOME/.cloudflared"
CONFIG_FILE="${CONFIG_DIR}/config.yml"

mkdir -p "$CONFIG_DIR"

if [ -n "$TUNNEL_HOSTNAME" ]; then
    # 有自定义域名
    cat > "$CONFIG_FILE" << EOF
tunnel: ${TUNNEL_ID}
credentials-file: ${CONFIG_DIR}/${TUNNEL_ID}.json

ingress:
  - hostname: ${TUNNEL_HOSTNAME}
    service: http://localhost:${PORT}
    originRequest:
      connectTimeout: 30s
      noTLSVerify: true
  - service: http_status:404
EOF
    log_info "配置文件已生成（域名模式）: $CONFIG_FILE"
else
    # 无自定义域名，使用 trycloudflare
    cat > "$CONFIG_FILE" << EOF
tunnel: ${TUNNEL_ID}
credentials-file: ${CONFIG_DIR}/${TUNNEL_ID}.json

ingress:
  - service: http://localhost:${PORT}
EOF
    log_info "配置文件已生成（trycloudflare 模式）: $CONFIG_FILE"
fi

# 启动隧道
log_info "启动 Cloudflared 隧道..."
$CLOUDFLARED tunnel run "$TUNNEL_NAME" &
TUNNEL_PID=$!

# 等待隧道就绪
sleep 3

# 显示访问地址
if [ -n "$TUNNEL_HOSTNAME" ]; then
    log_info "🌐 公网地址: https://${TUNNEL_HOSTNAME}"
else
    log_info "🌐 公网地址: 查看上方 cloudflared 输出的 trycloudflare.com 地址"
fi

log_info "📍 本地地址: http://localhost:${PORT}"
log_info "❤️  健康检查: http://localhost:${PORT}/api/health"

# 清理函数
cleanup() {
    log_info "正在关闭服务..."
    kill $TUNNEL_PID 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM

# 启动 Flask
log_info "启动 Flask 服务..."
cd "$PROJECT_DIR"
python app.py

# Flask 退出后清理
cleanup
