# Cloudflared 固定隧道配置指南

本文档说明如何配置 Cloudflare 固定隧道，实现稳定的公网访问地址。

## 前置要求

- Cloudflare 账号（免费）
- 已完成 venv 环境配置
- Flask 服务可正常运行

## 配置步骤

### 1. 设置环境变量

为方便使用，先设置 cloudflared 路径：

```bash
cd /home/xs/projects/tldw
source venv/bin/activate

# 设置 cloudflared 路径
export CLOUDFLARED="$(pwd)/venv/lib/python3.12/site-packages/pycloudflared/cloudflared-linux-amd64"

# 验证
$CLOUDFLARED --version
```

> **提示**：可将 `export CLOUDFLARED=...` 添加到 `~/.bashrc` 中永久生效。

### 2. 登录 Cloudflare

```bash
$CLOUDFLARED tunnel login
```

这会打开浏览器，选择一个域名授权（可以是任意已添加到 Cloudflare 的域名）。

登录成功后，凭证保存在 `~/.cloudflared/cert.pem`。

### 3. 创建隧道

```bash
# 创建名为 tldw-backend 的隧道
$CLOUDFLARED tunnel create tldw-backend
```

输出类似：
```
Tunnel credentials written to /home/xs/.cloudflared/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.json
Created tunnel tldw-backend with id xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

**记录隧道 ID**，后续配置需要用到。

### 4. 创建配置文件

创建 `~/.cloudflared/config.yml`：

```yaml
# Cloudflared 隧道配置
tunnel: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx  # 替换为你的隧道 ID
credentials-file: /home/xs/.cloudflared/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.json

ingress:
  # tldw 后端服务
  - hostname: tldw.你的域名.com  # 替换为你的子域名
    service: http://localhost:5123
    originRequest:
      connectTimeout: 30s
      noTLSVerify: true

  # 必须有的默认规则
  - service: http_status:404
```

### 5. 配置 DNS

将子域名指向隧道：

```bash
$CLOUDFLARED tunnel route dns tldw-backend tldw.你的域名.com
```

或者在 Cloudflare Dashboard 手动添加 CNAME 记录：
- 名称：`tldw`（或你选择的子域名）
- 目标：`xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.cfargotunnel.com`
- 代理状态：已代理（橙色云朵）

### 6. 测试隧道

```bash
# 启动隧道
$CLOUDFLARED tunnel run tldw-backend

# 另开终端测试
curl https://tldw.你的域名.com/api/health
```

### 7. 创建启动脚本

创建 `/home/xs/projects/tldw/start-tunnel.sh`：

```bash
#!/bin/bash

# tldw 隧道启动脚本

PROJECT_DIR="/home/xs/projects/tldw"
CLOUDFLARED="${PROJECT_DIR}/venv/lib/python3.12/site-packages/pycloudflared/cloudflared-linux-amd64"

echo "🚀 启动 tldw 服务..."

# 激活虚拟环境
source ${PROJECT_DIR}/venv/bin/activate

# 后台启动 cloudflared 隧道
echo "🌐 启动 Cloudflared 隧道..."
$CLOUDFLARED tunnel run tldw-backend &
TUNNEL_PID=$!
echo "✅ 隧道已启动 (PID: $TUNNEL_PID)"

# 等待隧道就绪
sleep 3

# 启动 Flask
echo "🌐 启动 Flask 服务..."
cd ${PROJECT_DIR}
python app.py

# Flask 退出时关闭隧道
echo "🛑 正在关闭隧道..."
kill $TUNNEL_PID 2>/dev/null
```

添加执行权限：
```bash
chmod +x /home/xs/projects/tldw/start-tunnel.sh
```

---

## 无自有域名方案

如果没有自己的域名，可以使用 Cloudflare 的免费 `trycloudflare.com` 子域名：

### 方案 A：临时隧道（URL 每次变化）

```bash
$CLOUDFLARED tunnel --url http://localhost:5123
```

### 方案 B：命名隧道 + trycloudflare（推荐）

1. 创建隧道（同上）：
```bash
$CLOUDFLARED tunnel create tldw-backend
```

2. 配置文件使用无域名模式 `~/.cloudflared/config.yml`：
```yaml
tunnel: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
credentials-file: /home/xs/.cloudflared/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.json

ingress:
  - service: http://localhost:5123
```

3. 启动隧道：
```bash
$CLOUDFLARED tunnel run tldw-backend
```

隧道会分配一个 `xxxxx.trycloudflare.com` 地址（每次启动可能变化）。

---

## 管理命令

```bash
# 查看所有隧道
$CLOUDFLARED tunnel list

# 查看隧道详情
$CLOUDFLARED tunnel info tldw-backend

# 删除隧道（需先停止）
$CLOUDFLARED tunnel delete tldw-backend

# 查看隧道连接状态
$CLOUDFLARED tunnel route ip show
```

---

## 故障排查

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| `tunnel not found` | 隧道未创建或名称错误 | 运行 `$CLOUDFLARED tunnel list` 检查 |
| `certificate error` | 未登录或凭证过期 | 重新运行 `$CLOUDFLARED tunnel login` |
| `connection refused` | Flask 未启动 | 确保 Flask 在 5123 端口运行 |
| DNS 解析失败 | DNS 未配置 | 检查 Cloudflare DNS 设置 |
| `502 Bad Gateway` | 后端服务异常 | 检查 Flask 日志 |

### 查看隧道日志

```bash
# 详细日志模式
$CLOUDFLARED tunnel --loglevel debug run tldw-backend
```

---

## 与 Vercel 集成

配置完成后，在 Vercel 项目的 `vercel.json` 中设置代理：

```json
{
  "rewrites": [
    {
      "source": "/api/:path*",
      "destination": "https://tldw.你的域名.com/api/:path*"
    }
  ]
}
```

或使用环境变量：
```
NEXT_PUBLIC_API_URL=https://tldw.你的域名.com
```

---

## 快速参考

| 项目 | 值 |
|------|-----|
| cloudflared 路径 | `venv/lib/python3.12/site-packages/pycloudflared/cloudflared-linux-amd64` |
| 凭证目录 | `~/.cloudflared/` |
| 配置文件 | `~/.cloudflared/config.yml` |
| Flask 端口 | `5123` |
| 健康检查 | `/api/health` |
