# YTQuickBite

YouTube 视频快速摘要工具 - 自动提取视频关键要点，节省你的时间。

## 架构

```
用户 → Vercel (前端) → Supabase (认证+数据库+存储) ← 本地 Worker (处理)
```

- **前端**: Next.js 部署在 Vercel
- **后端**: Supabase (PostgreSQL + Auth + Storage)
- **处理节点**: 本地运行 `worker.py`（GPU 加速转录）

## 功能特性

- 🔐 多用户支持（Google/GitHub 登录）
- 🎥 YouTube 音频下载
- 🎤 自动语音转文字（Whisper + GPU）
- 🤖 AI 内容分析和总结（GPT-4）
- 📄 生成交互式 HTML 简报
- 🔄 断点恢复（检查点系统）
- 📊 用户配额管理
- 🛡️ 防爬虫保护

## 快速开始

### 1. 配置 Supabase

1. 访问 [supabase.com](https://supabase.com) 创建项目
2. 在 SQL Editor 执行 `supabase/migrations/001_initial_schema.sql`
3. 创建 Storage Buckets: `reports`（公开）、`transcripts`（公开）
4. 启用 Google/GitHub OAuth

### 2. 部署前端 (Vercel)

```bash
cd ytquickbite-web
npm install
```

通过 GitHub 导入到 Vercel：
- Root Directory: `ytquickbite-web`
- 环境变量:
  - `NEXT_PUBLIC_SUPABASE_URL`
  - `NEXT_PUBLIC_SUPABASE_ANON_KEY`

### 3. 配置本地环境

```bash
cp .env.example .env
# 编辑 .env 填写 Supabase 和 OpenAI 配置
```

### 4. 启动 Worker

```bash
# 安装依赖
pip install -r requirements.txt

# 启动处理节点
./start_worker.sh
```

## 项目结构

```
tldw/
├── worker.py              # 本地处理节点（轮询 Supabase 任务）
├── supabase_client.py     # Supabase Python 客户端
├── video_processor.py     # 视频处理核心逻辑
├── start_worker.sh        # Worker 启动脚本
├── .env.example           # 环境变量模板
├── supabase/
│   └── migrations/        # 数据库 Schema
├── ytquickbite-web/       # Next.js 前端
│   ├── app/
│   │   ├── page.tsx       # 首页（公开视频）
│   │   ├── dashboard/     # 用户仪表板
│   │   └── report/        # 报告查看
│   └── lib/supabase.ts    # Supabase 客户端
├── downloads/             # 音频文件（本地缓存）
├── transcripts/           # 字幕文件（本地缓存）
└── docs/
    └── YTQUICKBITE_DEPLOYMENT.md  # 详细部署指南
```

## 处理流程

```
用户提交 YouTube URL
       ↓
Supabase 存储任务 (status: pending)
       ↓
本地 Worker 轮询获取任务
       ↓
┌─────────────────────────────────────┐
│ 1️⃣ 下载音频 (yt-dlp → MP3)          │
│ 2️⃣ 语音转录 (Whisper + GPU)         │
│ 3️⃣ AI 分析 (GPT-4)                  │
│ 4️⃣ 生成 HTML 简报                   │
└─────────────────────────────────────┘
       ↓
上传到 Supabase Storage
       ↓
用户查看报告
```

## 简报页面功能

- **点击跳转**: 点击字幕/要点跳转到对应时间
- **同步高亮**: 播放时自动高亮当前字幕
- **快捷键**: 空格播放/暂停，方向键快进/快退

## 环境变量

```bash
# Supabase
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SECRET_KEY=sb_secret_xxx

# 前端（自动读取）
NEXT_PUBLIC_SUPABASE_URL=https://xxx.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=sb_publishable_xxx

# OpenAI
OPENAI_API_KEY=sk-xxx
```

## 技术栈

- **前端**: Next.js, Tailwind CSS, Vercel
- **后端**: Supabase (PostgreSQL, Auth, Storage)
- **处理**: Python, yt-dlp, OpenAI Whisper, GPT-4
- **GPU**: PyTorch + CUDA（可选）

## 旧架构（本地模式）

如需使用旧的本地 Flask 模式：

```bash
./start.sh  # Flask + Cloudflare 隧道
```

## License

MIT
