# TLDW 开发文档

> Too Long; Didn't Watch - YouTube视频分析器

## 项目概述

TLDW是一个YouTube视频分析工具，可以自动下载视频音频、转录为文字、并生成摘要和关键要点。

## 技术栈

- **后端**: Flask (Python)
- **数据库**: SQLite
- **前端**: Jinja2模板 + 原生JavaScript
- **AI**: OpenAI GPT (内容分析) + Whisper (语音转录)
- **其他**: yt-dlp (视频下载)

## 项目结构

```
tldw/
├── app.py                 # Flask应用入口
├── database.py            # 数据库操作类
├── video_processor.py     # 视频处理核心逻辑
├── database.db            # SQLite数据库
├── .env                   # 环境变量配置
│
├── templates/             # Jinja2模板
│   ├── base.html         # 基础模板（导航、页脚）
│   ├── index.html        # 用户主页（视频展示）
│   └── dev.html          # 开发页面（提交表单、处理记录）
│
├── static/               # 静态资源
│   ├── css/
│   │   ├── common.css    # 公共样式
│   │   ├── home.css      # 主页样式
│   │   └── dev.css       # 开发页样式
│   └── js/
│       ├── common.js     # 公共脚本
│       └── dev.js        # 开发页脚本
│
├── downloads/            # 下载的音频文件 (*.mp3)
├── transcripts/          # 转录文件 (*.srt, *.txt)
├── reports/              # 生成的报告 (*.html)
│
└── docs/                 # 文档
    └── development.md    # 本文档
```

## 路由说明

| 路由 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 用户主页，展示已处理视频（卡片网格布局） |
| `/dev` | GET | 开发面板，提交视频、查看处理记录和日志 |
| `/submit` | POST | 提交YouTube链接开始处理 |
| `/status/<id>` | GET | 获取视频处理状态 |
| `/report/<filename>` | GET | 查看生成的报告 |
| `/api/videos` | GET | API: 获取所有视频列表 |
| `/api/logs/<id>` | GET | API: 获取处理日志 |
| `/api/delete/<id>/<type>` | DELETE | API: 删除文件或记录 |

## 模板继承结构

```
base.html
├── index.html (用户主页)
└── dev.html (开发页面)
```

### base.html

基础模板提供：
- 导航栏（首页/开发切换）
- 页脚
- CSS/JS引用
- Jinja2 blocks: `title`, `styles`, `content`, `scripts`

### index.html

用户主页特点：
- 响应式卡片网格布局
- 视频缩略图（来自YouTube）
- 标题、频道名、发布日期
- 点击跳转到报告页面

### dev.html

开发页面功能：
- 视频提交表单
- 处理记录表格（状态、文件状态、操作按钮）
- 实时日志区域

## 数据库结构

### videos 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| youtube_url | TEXT | YouTube链接 |
| video_title | TEXT | 视频标题 |
| report_filename | TEXT | 报告文件名 |
| status | TEXT | 状态: pending/processing/completed/failed |
| created_at | DATETIME | 创建时间 |
| completed_at | DATETIME | 完成时间 |
| error_message | TEXT | 错误信息 |
| whisper_model | TEXT | 使用的Whisper模型 |
| download_completed | INTEGER | 下载检查点 |
| transcribe_completed | INTEGER | 转录检查点 |
| report_completed | INTEGER | 报告检查点 |
| audio_file_path | TEXT | 音频文件路径 |
| transcript_file_path | TEXT | 转录文件路径 |
| publish_date | TEXT | 发布日期 (YYYYMMDD) |
| channel_name | TEXT | 频道名称 |
| duration | INTEGER | 视频时长（秒） |

## 环境配置

### .env 文件

```env
OPENAI_API_KEY=sk-your-api-key
OPENAI_BASE_URL=https://api.openai.com/v1
PORT=5001
```

### 依赖安装

```bash
# 创建conda环境
conda create -n tldw python=3.10
conda activate tldw

# 安装依赖
pip install flask flask-cors python-dotenv openai yt-dlp
pip install torch  # 或 pip install torch --index-url https://download.pytorch.org/whl/cu118

# Whisper安装
pip install openai-whisper
```

## 启动应用

```bash
# 激活环境
conda activate tldw

# 设置端口（可选）
export PORT=5123

# 启动
python app.py
```

访问地址：
- 主页: http://localhost:5123/
- 开发页: http://localhost:5123/dev

## 处理流程

1. **提交URL** → 解析视频ID，创建数据库记录
2. **下载音频** → 使用yt-dlp下载MP3，保存到 `downloads/`
3. **语音转录** → 使用Whisper生成SRT和TXT，保存到 `transcripts/`
4. **内容分析** → 使用OpenAI GPT生成摘要和关键要点
5. **生成报告** → 生成HTML报告，保存到 `reports/`
6. **完成** → 更新数据库状态为completed

## 检查点系统

支持断点恢复：
- `download_completed` - 音频下载完成
- `transcribe_completed` - 转录完成
- `report_completed` - 报告生成完成

如果处理中断，可以从上次的检查点继续。

## 开发注意事项

1. **API密钥**: 确保 `.env` 中的 `OPENAI_API_KEY` 有效
2. **磁盘空间**: 音频文件可能较大，注意磁盘空间
3. **GPU支持**: Whisper使用GPU会更快，但CPU也可用
4. **日志**: 查看控制台输出了解处理进度
