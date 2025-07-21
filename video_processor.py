import os
import yt_dlp
import whisper
import openai
import json
from datetime import datetime

class VideoProcessor:
    def __init__(self, database):
        self.db = database
        self.whisper_model = None
        self.openai_client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    
    def load_whisper_model(self):
        """延迟加载Whisper模型"""
        if self.whisper_model is None:
            print("Loading Whisper model...")
            self.whisper_model = whisper.load_model("base")
        return self.whisper_model
    
    def download_audio(self, youtube_url, video_id):
        """下载YouTube音频"""
        try:
            ydl_opts = {
                'format': 'bestaudio/best',
                'extractaudio': True,
                'audioformat': 'mp3',
                'outtmpl': f'downloads/%(title)s.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # 获取视频信息
                info = ydl.extract_info(youtube_url, download=False)
                video_title = info.get('title', 'Unknown Title')
                
                # 更新数据库中的视频标题
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('UPDATE videos SET video_title=? WHERE id=?', (video_title, video_id))
                    conn.commit()
                
                # 下载音频
                ydl.download([youtube_url])
                
                # 找到下载的文件
                safe_title = "".join(c for c in video_title if c.isalnum() or c in (' ', '-', '_')).rstrip()
                audio_file = f"downloads/{safe_title}.mp3"
                
                return audio_file, video_title
                
        except Exception as e:
            raise Exception(f"下载失败: {str(e)}")
    
    def transcribe_audio(self, audio_file):
        """使用Whisper转录音频"""
        try:
            model = self.load_whisper_model()
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
        try:
            # 更新状态为处理中
            self.db.update_video_status(video_id, 'processing')
            
            print(f"开始处理视频 {video_id}: {youtube_url}")
            
            # 1. 下载音频
            print("1. 下载音频...")
            audio_file, video_title = self.download_audio(youtube_url, video_id)
            
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
            error_msg = str(e)
            print(f"处理失败: {error_msg}")
            self.db.update_video_status(video_id, 'failed', error_msg)