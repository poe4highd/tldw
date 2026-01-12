# YTQuickBite 部署指南

## 架构概览

```
用户 → Vercel (前端) → Supabase (认证+数据库+存储) ← 本地 Worker (处理)
```

- **前端**: Next.js 部署在 Vercel
- **后端**: Supabase（PostgreSQL + Auth + Storage）
- **处理节点**: 你的电脑运行 `worker.py`

## 快速开始

### 1. 创建 Supabase 项目

1. 访问 [supabase.com](https://supabase.com) 并登录
2. 点击 "New Project"
3. 填写项目名称：`ytquickbite`
4. 选择离你最近的区域
5. 设置数据库密码（保存好）

### 2. 配置数据库

1. 进入项目后，点击左侧 "SQL Editor"
2. 复制 `supabase/migrations/001_initial_schema.sql` 的内容
3. 粘贴到编辑器并执行

### 3. 配置 Storage Buckets

1. 点击左侧 "Storage"
2. 点击 "New Bucket"
3. 创建两个 bucket：
   - 名称: `reports`，勾选 "Public bucket"
   - 名称: `transcripts`，勾选 "Public bucket"

### 4. 配置认证

1. 点击左侧 "Authentication" → "Providers"
2. 启用 Google:
   - 获取 [Google Cloud Console](https://console.cloud.google.com) 的 OAuth 凭据
   - 填写 Client ID 和 Client Secret
   - 重定向 URL: `https://你的项目.supabase.co/auth/v1/callback`
3. 启用 GitHub:
   - 在 [GitHub Developer Settings](https://github.com/settings/developers) 创建 OAuth App
   - 填写 Client ID 和 Client Secret
   - 重定向 URL: `https://你的项目.supabase.co/auth/v1/callback`

### 5. 获取 API Keys

1. 点击左侧 "Project Settings" → "API"
2. 记录以下信息：
   - **Project URL**: `https://xxx.supabase.co`
   - **anon public key**: `eyJ...`（前端使用）
   - **service_role secret key**: `eyJ...`（仅本地 Worker 使用，不要泄露）

## 前端部署 (Vercel)

### 1. 部署到 Vercel

```bash
cd ytquickbite-web
npm install
vercel
```

或者通过 GitHub 导入：
1. 将代码推送到 GitHub
2. 访问 [vercel.com](https://vercel.com)
3. 导入 `ytquickbite-web` 目录

### 2. 配置环境变量

在 Vercel 项目设置中添加：

| 变量名 | 值 |
|--------|-----|
| `NEXT_PUBLIC_SUPABASE_URL` | `https://你的项目.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | `eyJ...`（anon key） |

### 3. 更新 Supabase 重定向 URL

在 Supabase "Authentication" → "URL Configuration" 中：
- Site URL: `https://你的域名.vercel.app`
- Redirect URLs: 添加 `https://你的域名.vercel.app/auth/callback`

## 本地 Worker 部署

### 1. 安装依赖

```bash
cd /path/to/tldw
pip install -r requirements.txt
```

### 2. 配置环境变量

编辑 `.env` 文件：

```bash
# Supabase
SUPABASE_URL=https://你的项目.supabase.co
SUPABASE_SERVICE_KEY=eyJ...  # service_role key

# OpenAI
OPENAI_API_KEY=sk-...
```

### 3. 启动 Worker

```bash
python worker.py
```

Worker 会自动：
- 每 5 秒轮询待处理任务
- 每 30 秒发送心跳
- 处理视频并上传结果到 Supabase Storage

## 验证部署

1. 访问 `https://你的域名.vercel.app`
2. 点击登录（Google 或 GitHub）
3. 提交一个 YouTube URL
4. 检查本地 Worker 是否开始处理
5. 等待处理完成后查看报告

## 常见问题

### Worker 无法连接 Supabase

检查 `.env` 中的 `SUPABASE_URL` 和 `SUPABASE_SERVICE_KEY` 是否正确。

### OAuth 登录失败

确保 Supabase 中配置的重定向 URL 与 Vercel 域名匹配。

### 报告无法访问

确保 Storage bucket `reports` 是公开的。

### 配额不生效

检查 `user_quotas` 表是否正确创建了触发器。

## 监控

### 查看处理队列

```sql
SELECT status, COUNT(*) FROM videos GROUP BY status;
```

### 查看系统状态

```sql
SELECT * FROM system_status;
```

### 查看用户配额

```sql
SELECT u.email, q.* FROM user_quotas q
JOIN auth.users u ON u.id = q.user_id;
```

## 维护

### 每月重置配额

Supabase 免费版不支持 pg_cron，可以手动执行：

```sql
SELECT reset_monthly_quotas();
```

或设置外部定时任务调用 Supabase Edge Function。

### 清理旧数据

```sql
-- 删除 30 天前的失败任务
DELETE FROM videos
WHERE status = 'failed' AND created_at < NOW() - INTERVAL '30 days';
```

## 成本估算（Supabase 免费版）

| 资源 | 免费额度 | 预估使用 |
|------|----------|----------|
| 数据库 | 500 MB | ~1 KB/视频 |
| Storage | 1 GB | ~50 KB/报告 |
| Auth | 50,000 MAU | 足够 |
| API 请求 | 无限制 | - |

按此估算，免费版可存储约 20,000 个视频报告。
