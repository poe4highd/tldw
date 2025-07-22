import os
import sys
import sqlite3
import yt_dlp
import whisper
import openai
import json
import re
from datetime import datetime

class VideoProcessor:
    def __init__(self, database):
        self.db = database
        self.whisper_model = None
        self.openai_client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        self.log_messages = []  # 存储详细日志消息
    
    def log(self, message):
        """添加日志消息"""
        print(message)  # 服务器端日志
        self.log_messages.append(message)  # 收集用于前端显示
    
    def get_logs(self):
        """获取收集的日志"""
        return '\n'.join(self.log_messages)
    
    def clear_logs(self):
        """清除日志"""
        self.log_messages = []
    
    def extract_video_id(self, youtube_url):
        """从YouTube URL提取视频ID"""
        # 支持多种YouTube URL格式
        patterns = [
            r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([^&\n?#]+)',
            r'youtube\.com/watch\?.*v=([^&\n?#]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, youtube_url)
            if match:
                video_id = match.group(1)
                # YouTube视频ID通常是11个字符
                if len(video_id) == 11:
                    return video_id
        
        # 如果无法提取，抛出异常
        raise ValueError(f"无法从URL提取视频ID: {youtube_url}")
    
    def load_whisper_model(self):
        """延迟加载Whisper模型 - 使用tiny模型"""
        if self.whisper_model is None:
            self.log("🤖 Loading Whisper tiny model...")
            self.whisper_model = whisper.load_model("tiny")
        return self.whisper_model
    
    def download_audio_fallback(self, youtube_url, video_id):
        """备用下载方法 - 使用最简配置"""
        strategies = [
            # 策略1: 使用Android客户端
            {
                'format': 'bestaudio/best',
                'outtmpl': f'downloads/%(title)s.%(ext)s',
                'extractor_args': {'youtube': {'player_client': ['android']}},
                'user_agent': 'com.google.android.youtube/17.31.35 (Linux; U; Android 11) gzip',
            },
            # 策略2: 使用iOS客户端
            {
                'format': 'bestaudio/best', 
                'outtmpl': f'downloads/%(title)s.%(ext)s',
                'extractor_args': {'youtube': {'player_client': ['ios']}},
                'user_agent': 'com.google.ios.youtube/17.31.4 (iPhone; CPU iPhone OS 15_6 like Mac OS X)',
            },
            # 策略3: 最基本配置
            {
                'format': 'worst[ext=webm]/worst',
                'outtmpl': f'downloads/%(title)s.%(ext)s',
                'no_warnings': True,
                'quiet': True,
            }
        ]
        
        for i, ydl_opts in enumerate(strategies, 1):
            try:
                self.log(f"📱 尝试备用策略 {i}...")
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(youtube_url, download=False)
                    video_title = info.get('title', 'Unknown Title')
                    
                    # 更新数据库中的视频标题
                    with sqlite3.connect(self.db.db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute('UPDATE videos SET video_title=? WHERE id=?', (video_title, video_id))
                        conn.commit()
                    
                    # 下载音频
                    ydl.download([youtube_url])
                    
                    # 找到下载的文件
                    safe_title = "".join(c for c in video_title if c.isalnum() or c in (' ', '-', '_')).rstrip()
                    # 检查可能的文件格式
                    for ext in ['.webm', '.mp4', '.m4a', '.mp3']:
                        audio_file = f"downloads/{safe_title}{ext}"
                        if os.path.exists(audio_file):
                            return audio_file, video_title
                    
                    raise Exception("找不到下载的音频文件")
                    
            except Exception as e:
                self.log(f"❌ 备用策略 {i} 失败: {str(e)}")
                continue
        
        raise Exception("所有备用策略都失败了")

    def download_audio_final_fallback(self, youtube_url, video_id):
        """最终备用方案 - 复制测试脚本的确切配置"""
        try:
            self.log("🎯 使用测试脚本验证的确切配置...")
            
            # 完全复制测试脚本中成功的配置
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': f'downloads/final_%(title)s.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'referer': 'https://www.youtube.com/',
                'extractor_args': {
                    'youtube': {
                        'skip': ['dash'],
                        'player_skip': ['js'],
                        'player_client': ['web', 'android'],
                    }
                },
                'cookiesfrombrowser': ('firefox', None, None, None),
                'http_headers': {
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Encoding': 'gzip, deflate',
                    'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.3',
                    'Connection': 'keep-alive',
                },
                'no_warnings': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                self.log("📋 获取视频信息...")
                info = ydl.extract_info(youtube_url, download=False)
                video_title = info.get('title', 'Unknown Title')
                
                self.log(f"✅ 视频标题: {video_title}")
                
                # 更新数据库中的视频标题
                with sqlite3.connect(self.db.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute('UPDATE videos SET video_title=? WHERE id=?', (video_title, video_id))
                    conn.commit()
                
                self.log("⬇️ 开始下载...")
                ydl.download([youtube_url])
                
                # 找到下载的文件
                safe_title = "".join(c for c in video_title if c.isalnum() or c in (' ', '-', '_')).rstrip()
                audio_file = f"downloads/final_{safe_title}.mp3"
                
                if os.path.exists(audio_file):
                    self.log(f"🎉 下载成功: {audio_file}")
                    return audio_file, video_title
                else:
                    # 尝试寻找其他可能的文件名
                    for prefix in ['final_', '']:
                        for ext in ['.mp3', '.m4a', '.webm', '.mp4']:
                            test_file = f"downloads/{prefix}{safe_title}{ext}"
                            if os.path.exists(test_file):
                                return test_file, video_title
                    
                    raise Exception("找不到下载的文件")
                
        except Exception as e:
            raise Exception(f"最终备用方案失败: {str(e)}")

    def download_audio_ultra_simple(self, youtube_url, video_id):
        """终极简化方案 - 最基本的配置"""
        try:
            print("使用终极简化配置...")
            
            # 最简单的配置，只下载不转换
            ydl_opts = {
                'outtmpl': f'downloads/ultra_%(title)s.%(ext)s',
                'format': 'worst',
                'quiet': False,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                print("获取视频信息...")
                info = ydl.extract_info(youtube_url, download=False)
                video_title = info.get('title', 'Unknown Title')
                
                print(f"视频标题: {video_title}")
                
                # 更新数据库
                with sqlite3.connect(self.db.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute('UPDATE videos SET video_title=? WHERE id=?', (video_title, video_id))
                    conn.commit()
                
                print("开始下载 (不转换格式)...")
                ydl.download([youtube_url])
                
                # 查找下载的文件
                safe_title = "".join(c for c in video_title if c.isalnum() or c in (' ', '-', '_')).rstrip()
                
                # 查找可能的文件
                import glob
                pattern = f"downloads/ultra_{safe_title}.*"
                files = glob.glob(pattern)
                
                if files:
                    audio_file = files[0]  # 使用第一个匹配的文件
                    print(f"找到文件: {audio_file}")
                    return audio_file, video_title
                else:
                    # 列出downloads目录的所有文件
                    import os
                    if os.path.exists('downloads'):
                        all_files = os.listdir('downloads')
                        ultra_files = [f for f in all_files if f.startswith('ultra_')]
                        if ultra_files:
                            audio_file = f"downloads/{ultra_files[0]}"
                            return audio_file, video_title
                    
                    raise Exception("找不到下载的文件")
                
        except Exception as e:
            raise Exception(f"终极简化方案也失败: {str(e)}")

    def download_audio(self, youtube_url, video_id):
        """下载YouTube音频 - 使用视频ID作为文件名"""
        try:
            self.clear_logs()  # 清除之前的日志
            
            # 提取YouTube视频ID
            try:
                yt_video_id = self.extract_video_id(youtube_url)
                self.log(f"✅ 提取视频ID: {yt_video_id}")
            except ValueError as e:
                self.log(f"❌ {str(e)}")
                raise
            
            self.log("="*60)
            self.log("🎯 开始YouTube下载过程")
            self.log(f"📹 URL: {youtube_url}")
            self.log(f"🆔 数据库ID: {video_id}")
            self.log(f"🎬 YouTube视频ID: {yt_video_id}")
            self.log("🔧 策略: 使用视频ID作为文件名")
            self.log("="*60)
            
            # 使用视频ID作为文件名的配置
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': f'downloads/{yt_video_id}.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'referer': 'https://www.youtube.com/',
                'extractor_args': {
                    'youtube': {
                        'skip': ['dash'],
                        'player_skip': ['js'],
                        'player_client': ['web', 'android'],
                    }
                },
                'http_headers': {
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Encoding': 'gzip, deflate',
                    'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.3',
                    'Connection': 'keep-alive',
                },
                'no_warnings': True,
            }
            
            # 添加详细的环境和配置日志
            self.log(f"📱 Flask进程环境信息:")
            self.log(f"   🐍 Python执行路径: {sys.executable}")
            self.log(f"   📂 当前工作目录: {os.getcwd()}")
            self.log(f"   📦 yt-dlp版本: {yt_dlp.version.__version__}")
            
            self.log(f"🔧 yt-dlp配置:")
            self.log(f"   🎵 格式: {ydl_opts['format']}")
            self.log(f"   🕷️ User-Agent: {ydl_opts['user_agent'][:50]}...")
            self.log(f"   🔗 Referer: {ydl_opts.get('referer', '未设置')}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                self.log("📋 开始获取视频信息...")
                info = ydl.extract_info(youtube_url, download=False)
                video_title = info.get('title', 'Unknown Title')
                
                self.log(f"✅ 视频标题: {video_title}")
                self.log(f"✅ 视频时长: {info.get('duration', 'Unknown')}秒")
                self.log(f"✅ 上传者: {info.get('uploader', 'Unknown')}")
                
                # 更新数据库中的视频标题
                with sqlite3.connect(self.db.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute('UPDATE videos SET video_title=? WHERE id=?', (video_title, video_id))
                    conn.commit()
                
                self.log("⬇️ 开始下载...")
                ydl.download([youtube_url])
                
                # 使用视频ID查找下载的文件
                expected_mp3 = f"downloads/{yt_video_id}.mp3"
                
                # 首先检查MP3文件（转换后的目标格式）
                if os.path.exists(expected_mp3):
                    file_size = os.path.getsize(expected_mp3) / (1024 * 1024)  # MB
                    self.log(f"🎉 下载成功: {expected_mp3} ({file_size:.2f} MB)")
                    return expected_mp3, video_title
                
                # 检查其他可能的格式（未转换的原始格式）
                for ext in ['.m4a', '.webm', '.mp4']:
                    test_file = f"downloads/{yt_video_id}{ext}"
                    if os.path.exists(test_file):
                        file_size = os.path.getsize(test_file) / (1024 * 1024)  # MB
                        self.log(f"🎉 下载成功 (格式: {ext}): {test_file} ({file_size:.2f} MB)")
                        return test_file, video_title
                
                # 如果都找不到，列出downloads目录内容进行调试
                self.log("🔍 downloads目录内容:")
                try:
                    for f in os.listdir("downloads"):
                        if f.startswith(yt_video_id):
                            self.log(f"   📄 找到相关文件: {f}")
                except Exception as e:
                    self.log(f"   ❌ 无法列出目录: {e}")
                
                raise Exception(f"找不到视频ID为 {yt_video_id} 的下载文件")
                
        except Exception as e:
            self.log("❌ Android客户端策略失败!")
            self.log(f"🔍 错误详情: {str(e)}")
            self.log("\n" + "="*60)
            self.log("🔄 尝试iOS客户端备用策略")
            self.log("="*60)
            
            try:
                # 尝试iOS客户端
                self.log("📱 使用iOS客户端配置...")
                ios_opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': f'downloads/%(title)s.%(ext)s',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                    'extractor_args': {'youtube': {'player_client': ['ios']}},
                    'user_agent': 'com.google.ios.youtube/17.31.4 (iPhone; CPU iPhone OS 15_6 like Mac OS X)',
                    'no_warnings': True,
                }
                
                with yt_dlp.YoutubeDL(ios_opts) as ydl:
                    info = ydl.extract_info(youtube_url, download=False)
                    video_title = info.get('title', 'Unknown Title')
                    self.log(f"✅ iOS策略获取标题: {video_title}")
                    
                    # 更新数据库
                    with sqlite3.connect(self.db.db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute('UPDATE videos SET video_title=? WHERE id=?', (video_title, video_id))
                        conn.commit()
                    
                    ydl.download([youtube_url])
                    
                    # 查找文件
                    safe_title = "".join(c for c in video_title if c.isalnum() or c in (' ', '-', '_')).rstrip()
                    for ext in ['.mp3', '.m4a', '.webm', '.mp4']:
                        audio_file = f"downloads/{safe_title}{ext}"
                        if os.path.exists(audio_file):
                            self.log(f"🎉 iOS策略成功: {audio_file}")
                            return audio_file, video_title
                    
                    raise Exception("iOS策略下载完成但找不到文件")
                    
            except Exception as ios_error:
                self.log("❌ iOS策略也失败!")
                self.log(f"🔍 错误详情: {str(ios_error)}")
                
                # 最简化策略 - 只下载不转换
                self.log("\n🚀 尝试最简化策略 (不转换格式)...")
                try:
                    simple_opts = {
                        'format': 'worst[ext=webm]/worst',
                        'outtmpl': f'downloads/%(title)s.%(ext)s',
                        'no_warnings': True,
                    }
                    
                    with yt_dlp.YoutubeDL(simple_opts) as ydl:
                        info = ydl.extract_info(youtube_url, download=False)
                        video_title = info.get('title', 'Unknown Title')
                        self.log(f"✅ 最简策略获取标题: {video_title}")
                        
                        # 更新数据库
                        with sqlite3.connect(self.db.db_path) as conn:
                            cursor = conn.cursor()
                            cursor.execute('UPDATE videos SET video_title=? WHERE id=?', (video_title, video_id))
                            conn.commit()
                        
                        ydl.download([youtube_url])
                        
                        # 查找任意格式的文件
                        safe_title = "".join(c for c in video_title if c.isalnum() or c in (' ', '-', '_')).rstrip()
                        for ext in ['.webm', '.mp4', '.m4a', '.mp3']:
                            audio_file = f"downloads/{safe_title}{ext}"
                            if os.path.exists(audio_file):
                                self.log(f"🎉 最简策略成功: {audio_file}")
                                return audio_file, video_title
                        
                        raise Exception("最简策略下载完成但找不到文件")
                        
                except Exception as simple_error:
                    self.log("❌ 所有策略都失败了!")
                    
                    # 获取完整的日志信息
                    detailed_logs = self.get_logs()
                    error_summary = f"""所有下载策略都失败了！

详细日志:
{detailed_logs}

错误汇总:
1️⃣ Android策略: {str(e)}
2️⃣ iOS策略: {str(ios_error)}
3️⃣ 最简策略: {str(simple_error)}"""
                    raise Exception(error_summary)
    
    def transcribe_audio(self, audio_file):
        """使用Whisper转录音频"""
        try:
            model = self.load_whisper_model()
            print(f"开始转录音频文件: {audio_file}")
            result = model.transcribe(audio_file)
            
            # 生成SRT格式字幕
            srt_content = self.generate_srt(result['segments'])
            
            # 保存SRT文件
            base_name = os.path.splitext(os.path.basename(audio_file))[0]
            srt_file = f"transcripts/{base_name}.srt"
            
            with open(srt_file, 'w', encoding='utf-8') as f:
                f.write(srt_content)
            
            return result['text'], srt_file, result['segments']
            
        except Exception as e:
            raise Exception(f"语音转录失败: {str(e)}")
    
    def generate_srt(self, segments):
        """生成SRT格式字幕"""
        srt_content = ""
        for i, segment in enumerate(segments):
            start_time = self.seconds_to_srt_time(segment['start'])
            end_time = self.seconds_to_srt_time(segment['end'])
            text = segment['text'].strip()
            
            srt_content += f"{i+1}\n"
            srt_content += f"{start_time} --> {end_time}\n"
            srt_content += f"{text}\n\n"
        
        return srt_content
    
    def seconds_to_srt_time(self, seconds):
        """将秒数转换为SRT时间格式"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millisecs = int((seconds % 1) * 1000)
        
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millisecs:03d}"
    
    def analyze_content(self, transcript, segments):
        """使用AI分析内容并生成简报"""
        try:
            # 构建分析提示
            prompt = f"""
请分析以下YouTube视频的文字稿，并生成一份简报：

文字稿内容：
{transcript}

请按以下格式输出JSON：
{{
    "summary": "视频主要内容的简洁总结（3-5句话）",
    "key_points": [
        {{
            "point": "要点描述",
            "explanation": "详细解释",
            "timestamp": "起始时间（秒）",
            "quote": "原文引用（如果有的话）"
        }}
    ]
}}

要求：
1. 提取3-8个关键要点
2. 每个要点都要包含对应的时间戳
3. 要点应该涵盖视频的主要观点和重要信息
4. 时间戳要准确对应到相关内容
"""

            response = self.openai_client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )
            
            analysis = json.loads(response.choices[0].message.content)
            return analysis
            
        except Exception as e:
            raise Exception(f"内容分析失败: {str(e)}")
    
    def generate_report_html(self, video_title, youtube_url, analysis, srt_file):
        """生成HTML简报"""
        try:
            html_content = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{video_title} - 视频简报</title>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #f5f5f5; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
        .summary {{ background: #e8f4fd; padding: 15px; border-radius: 8px; margin-bottom: 20px; }}
        .key-point {{ background: white; border: 1px solid #ddd; padding: 15px; margin-bottom: 15px; border-radius: 8px; }}
        .timestamp {{ background: #007bff; color: white; padding: 4px 8px; border-radius: 4px; text-decoration: none; }}
        .timestamp:hover {{ background: #0056b3; }}
        .quote {{ font-style: italic; color: #666; margin-top: 10px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{video_title}</h1>
        <p><strong>原视频链接：</strong> <a href="{youtube_url}" target="_blank">{youtube_url}</a></p>
        <p><strong>生成时间：</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </div>
    
    <div class="summary">
        <h2>📋 内容摘要</h2>
        <p>{analysis['summary']}</p>
    </div>
    
    <div class="key-points">
        <h2>🔑 关键要点</h2>
"""
            
            for i, point in enumerate(analysis['key_points'], 1):
                timestamp_seconds = point.get('timestamp', 0)
                timestamp_url = f"{youtube_url}&t={int(timestamp_seconds)}s"
                timestamp_display = self.seconds_to_display_time(timestamp_seconds)
                
                html_content += f"""
        <div class="key-point">
            <h3>{i}. {point['point']}</h3>
            <p>{point['explanation']}</p>
            <p><a href="{timestamp_url}" target="_blank" class="timestamp">⏰ {timestamp_display}</a></p>
            {f'<div class="quote">"{point["quote"]}"</div>' if point.get('quote') else ''}
        </div>
"""
            
            html_content += """
    </div>
</body>
</html>
"""
            
            # 保存HTML文件
            safe_title = "".join(c for c in video_title if c.isalnum() or c in (' ', '-', '_')).rstrip()
            report_filename = f"{safe_title}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            report_path = f"reports/{report_filename}"
            
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            return report_filename
            
        except Exception as e:
            raise Exception(f"生成简报失败: {str(e)}")
    
    def seconds_to_display_time(self, seconds):
        """将秒数转换为显示格式"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes:02d}:{secs:02d}"
    
    def process_video(self, video_id, youtube_url):
        """完整的视频处理流程"""
        print("="*80)
        print(f"🎬 VIDEO_PROCESSOR: process_video方法被调用")
        print(f"   📹 video_id: {video_id}")
        print(f"   🔗 youtube_url: {youtube_url}")
        print(f"   🗄️ database对象: {type(self.db)}")
        print("="*80)
        
        try:
            print("📝 更新数据库状态为processing...")
            # 更新状态为处理中
            self.db.update_video_status(video_id, 'processing')
            print("✅ 数据库状态更新完成")
            
            print(f"🚀 开始处理视频 {video_id}: {youtube_url}")
            
            # 1. 下载音频
            print("1️⃣ 准备下载音频...")
            print(f"   调用download_audio({youtube_url}, {video_id})")
            audio_file, video_title = self.download_audio(youtube_url, video_id)
            print(f"✅ 下载音频完成: {audio_file}")
            
            # 2. 语音转录
            print("2. 语音转录...")
            transcript, srt_file, segments = self.transcribe_audio(audio_file)
            
            # 3. AI分析
            print("3. AI内容分析...")
            analysis = self.analyze_content(transcript, segments)
            
            # 4. 生成简报
            print("4. 生成HTML简报...")
            report_filename = self.generate_report_html(video_title, youtube_url, analysis, srt_file)
            
            # 5. 更新数据库
            self.db.update_report_filename(video_id, report_filename)
            self.db.update_video_status(video_id, 'completed')
            
            print(f"视频处理完成: {report_filename}")
            
        except Exception as e:
            import traceback
            error_msg = str(e)
            detailed_traceback = traceback.format_exc()
            
            print("="*80)
            print("❌ VIDEO_PROCESSOR: process_video异常!")
            print(f"   🚨 错误信息: {error_msg}")
            print(f"   📍 详细堆栈:")
            print(detailed_traceback)
            print("="*80)
            
            print(f"📊 更新数据库状态为failed...")
            self.db.update_video_status(video_id, 'failed', error_msg)