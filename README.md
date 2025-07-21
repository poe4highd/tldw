# YouTube视频分析器

一个基于Flask的YouTube视频分析工具，可以自动下载音频、生成字幕、AI分析内容并生成简报。

## 功能特性

- 🎥 YouTube音频下载
- 🎤 自动语音转文字（Whisper）
- 🤖 AI内容分析和总结（GPT-4）
- 📄 生成带时间戳的HTML简报
- 💾 SQLite数据库存储

## 快速开始

### 1. 环境要求

- Python 3.8+
- FFmpeg（用于音频处理）

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

复制 `.env` 文件并配置：

```bash
OPENAI_API_KEY=your_openai_api_key_here
FLASK_ENV=development
FLASK_DEBUG=True
```

### 4. 运行应用

```bash
python app.py
```

访问 http://localhost:5000

## 项目结构

```
tldw/
├── app.py              # Flask主应用
├── database.py         # 数据库操作
├── video_processor.py  # 视频处理核心逻辑
├── requirements.txt    # Python依赖
├── .env               # 环境变量配置
├── templates/         # HTML模板
│   └── index.html
├── downloads/         # 音频文件存储
├── transcripts/       # 字幕文件存储
└── reports/          # HTML简报存储
```

## 使用说明

1. 在主页输入YouTube视频链接
2. 系统自动下载音频并转换为文字
3. AI分析内容并提取关键要点
4. 生成包含时间戳链接的HTML简报
5. 点击时间戳可直接跳转到YouTube视频对应位置

## 技术栈

- **后端**: Flask, SQLite
- **音频下载**: yt-dlp
- **语音识别**: OpenAI Whisper
- **AI分析**: OpenAI GPT-4
- **前端**: HTML/CSS/JavaScript

## 注意事项

- 需要配置OpenAI API密钥
- 首次运行会下载Whisper模型
- 处理时间取决于视频长度和网络速度