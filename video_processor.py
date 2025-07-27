import os
import sys
import sqlite3
import yt_dlp
import whisper
import openai
import json
import re
from datetime import datetime

class Checkpoint:
    """检查点常量定义"""
    DOWNLOAD = "download"
    TRANSCRIBE = "transcribe" 
    REPORT = "report"
    
class CheckpointStatus:
    """检查点状态常量"""
    PENDING = 0
    COMPLETED = 1
    FAILED = -1

class VideoProcessor:
    def __init__(self, database):
        self.db = database
        self.whisper_model = None
        self.openai_client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        self.log_messages = []  # 存储详细日志消息
        self.device = None  # 缓存设备信息
        
        # Whisper模型优先级 (数值越高优先级越高)
        self.model_priority = {
            'tiny': 1,
            'base': 2,
            'small': 3,
            'medium': 4,
            'large': 5,
            'large-v2': 6,
            'large-v3': 7
        }
    
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
    
    def get_optimal_device(self):
        """获取最优设备配置"""
        if self.device is None:
            import torch
            
            if torch.cuda.is_available():
                # 检查GPU内存
                gpu_memory = torch.cuda.get_device_properties(0).total_memory / 1024**3  # GB
                self.device = {
                    'type': 'cuda',
                    'name': torch.cuda.get_device_name(0),
                    'memory': f"{gpu_memory:.1f}GB",
                    'optimal_model': 'medium' if gpu_memory > 4 else 'base'
                }
                self.log(f"🎮 检测到GPU: {self.device['name']} ({self.device['memory']})")
            else:
                # CPU配置
                import psutil
                cpu_count = psutil.cpu_count()
                memory_gb = psutil.virtual_memory().total / 1024**3
                self.device = {
                    'type': 'cpu',
                    'name': f"{cpu_count}核CPU",
                    'memory': f"{memory_gb:.1f}GB",
                    'optimal_model': 'tiny' if memory_gb < 8 else 'base'
                }
                self.log(f"💻 使用CPU: {self.device['name']} ({self.device['memory']})")
        
        return self.device
    
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
        """延迟加载Whisper模型 - 智能选择模型和设备"""
        if self.whisper_model is None:
            # 获取最优设备配置
            device_info = self.get_optimal_device()
            device = device_info['type']
            model_name = device_info['optimal_model']
            
            self.log(f"🤖 Loading Whisper {model_name} model on {device}...")
            self.log(f"📊 硬件配置: {device_info['name']} ({device_info['memory']})")
            
            try:
                # 加载模型时添加更多配置
                if device == "cuda":
                    import torch
                    # 清理GPU内存
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                    
                self.whisper_model = whisper.load_model(model_name, device=device)
                self.log(f"✅ Whisper {model_name} 模型加载完成 (设备: {device})")
                
                # 显示模型信息
                model_params = sum(p.numel() for p in self.whisper_model.parameters()) / 1e6
                self.log(f"📊 模型参数量: {model_params:.1f}M")
                
            except Exception as e:
                # 如果首选模型加载失败，回退到最小模型
                self.log(f"⚠️ {model_name}模型加载失败，回退到tiny模型: {str(e)}")
                try:
                    self.whisper_model = whisper.load_model("tiny", device="cpu")
                    self.log("✅ Whisper tiny模型加载完成 (设备: CPU)")
                except Exception as fallback_error:
                    raise Exception(f"Whisper模型加载完全失败: {str(fallback_error)}")
                
        return self.whisper_model
    
    def should_reanalyze_with_better_model(self, video_id, current_model):
        """检查是否应该使用更好的模型重新分析"""
        # 获取该视频之前使用的模型
        previous_model = self.db.get_video_whisper_model(video_id)
        
        if not previous_model:
            # 首次分析，记录当前模型
            self.db.update_whisper_model(video_id, current_model)
            return False, None
        
        # 比较模型优先级
        current_priority = self.model_priority.get(current_model, 0)
        previous_priority = self.model_priority.get(previous_model, 0)
        
        if current_priority > previous_priority:
            self.log(f"🔄 检测到模型升级: {previous_model} → {current_model}")
            self.log(f"📈 模型优先级提升: {previous_priority} → {current_priority}")
            return True, previous_model
        
        return False, previous_model
    
    # 检查点验证和管理方法
    def validate_checkpoint_status(self, video_id):
        """验证所有检查点状态，确保文件存在性"""
        self.log(f"🔍 验证视频 {video_id} 的检查点状态...")
        
        checkpoint_status = self.db.get_checkpoint_status(video_id)
        if not checkpoint_status:
            self.log(f"❌ 无法获取视频 {video_id} 的检查点状态")
            return None
        
        # 验证下载检查点
        download_valid = False
        if checkpoint_status['download_completed']:
            audio_path = checkpoint_status['audio_file_path']
            if audio_path and os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
                download_valid = True
                self.log(f"✅ 下载检查点验证通过: {audio_path}")
            else:
                self.log(f"❌ 下载检查点失效: 文件不存在或为空")
                self.db.reset_checkpoint(video_id, Checkpoint.DOWNLOAD)
        
        # 验证转录检查点
        transcribe_valid = False
        if checkpoint_status['transcribe_completed']:
            transcript_path = checkpoint_status['transcript_file_path']
            if transcript_path:
                # 检查SRT和TXT文件
                srt_file = transcript_path if transcript_path.endswith('.srt') else transcript_path + '.srt'
                txt_file = transcript_path.replace('.srt', '.txt') if transcript_path.endswith('.srt') else transcript_path + '.txt'
                
                if (os.path.exists(srt_file) and os.path.getsize(srt_file) > 0 and 
                    os.path.exists(txt_file) and os.path.getsize(txt_file) > 0):
                    transcribe_valid = True
                    self.log(f"✅ 转录检查点验证通过: {srt_file}, {txt_file}")
                else:
                    self.log(f"❌ 转录检查点失效: 转录文件不存在或为空")
                    self.db.reset_checkpoint(video_id, Checkpoint.TRANSCRIBE)
        
        # 验证简报检查点
        report_valid = False
        if checkpoint_status['report_completed']:
            report_filename = checkpoint_status['report_filename']
            if report_filename:
                report_path = f"reports/{report_filename}"
                if os.path.exists(report_path) and os.path.getsize(report_path) > 0:
                    report_valid = True
                    self.log(f"✅ 简报检查点验证通过: {report_path}")
                else:
                    self.log(f"❌ 简报检查点失效: 简报文件不存在或为空")
                    self.db.reset_checkpoint(video_id, Checkpoint.REPORT)
        
        return {
            'download_valid': download_valid,
            'transcribe_valid': transcribe_valid,
            'report_valid': report_valid,
            'checkpoint_status': checkpoint_status
        }
    
    def get_next_checkpoint(self, video_id):
        """确定下一个需要执行的检查点"""
        validation = self.validate_checkpoint_status(video_id)
        if not validation:
            return Checkpoint.DOWNLOAD
        
        if not validation['download_valid']:
            self.log(f"📍 下一个检查点: {Checkpoint.DOWNLOAD}")
            return Checkpoint.DOWNLOAD
        elif not validation['transcribe_valid']:
            self.log(f"📍 下一个检查点: {Checkpoint.TRANSCRIBE}")
            return Checkpoint.TRANSCRIBE
        elif not validation['report_valid']:
            self.log(f"📍 下一个检查点: {Checkpoint.REPORT}")
            return Checkpoint.REPORT
        else:
            self.log(f"✅ 所有检查点都已完成")
            return None
    
    def is_fully_completed(self, video_id):
        """检查视频是否完全处理完成"""
        validation = self.validate_checkpoint_status(video_id)
        if not validation:
            return False
        
        return (validation['download_valid'] and 
                validation['transcribe_valid'] and 
                validation['report_valid'])
    
    def sync_checkpoints_with_files(self, video_id):
        """同步文件状态到数据库检查点"""
        self.log(f"🔄 同步视频 {video_id} 的文件状态到检查点...")
        
        # 这将通过validate_checkpoint_status自动重置失效的检查点
        self.validate_checkpoint_status(video_id)
        self.log(f"✅ 检查点同步完成")
    
    def get_current_optimal_model(self):
        """获取当前环境下的最优模型"""
        device_info = self.get_optimal_device()
        return device_info['optimal_model']
    
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
            
            # 检查MP3文件是否已存在
            expected_mp3 = f"downloads/{yt_video_id}.mp3"
            if os.path.exists(expected_mp3):
                file_size = os.path.getsize(expected_mp3) / (1024 * 1024)  # MB
                self.log(f"🎉 发现已存在的MP3文件: {expected_mp3} ({file_size:.2f} MB)")
                self.log("⏭️ 跳过下载，直接使用现有文件")
                
                # 从数据库获取视频标题，如果没有则尝试获取
                with sqlite3.connect(self.db.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute('SELECT video_title FROM videos WHERE id=?', (video_id,))
                    result = cursor.fetchone()
                    video_title = result[0] if result and result[0] else None
                
                # 如果数据库中没有标题，则获取视频信息
                if not video_title:
                    self.log("📋 获取视频标题信息...")
                    ydl_opts = {'quiet': True}
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(youtube_url, download=False)
                        video_title = info.get('title', 'Unknown Title')
                        # 更新数据库中的视频标题
                        with sqlite3.connect(self.db.db_path) as conn:
                            cursor = conn.cursor()
                            cursor.execute('UPDATE videos SET video_title=? WHERE id=?', (video_title, video_id))
                            conn.commit()
                        self.log(f"✅ 视频标题: {video_title}")
                
                return expected_mp3, video_title
            
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
    
    def transcribe_audio(self, audio_file, force_retranscribe=False):
        """使用Whisper转录音频"""
        try:
            # 检查转录文件是否已存在
            base_name = os.path.splitext(os.path.basename(audio_file))[0]
            srt_file = f"transcripts/{base_name}.srt"
            transcript_file = f"transcripts/{base_name}.txt"
            
            if not force_retranscribe and os.path.exists(srt_file) and os.path.exists(transcript_file):
                self.log(f"🎉 发现已存在的转录文件: {srt_file}")
                self.log("⏭️ 跳过转录，直接使用现有文件")
                
                # 读取现有的转录文本
                with open(transcript_file, 'r', encoding='utf-8') as f:
                    transcript_text = f.read()
                
                # 解析SRT文件获取segments信息，并合并短片段
                raw_segments = self.parse_srt_file(srt_file)
                merged_segments = self.merge_short_segments(raw_segments)
                
                self.log(f"📊 原始片段数: {len(raw_segments)}, 合并后片段数: {len(merged_segments)}")
                
                return transcript_text, srt_file, merged_segments
            
            if force_retranscribe:
                self.log(f"🔄 强制重新转录 (使用更好的模型)")
            elif os.path.exists(srt_file) or os.path.exists(transcript_file):
                self.log(f"🔄 覆盖现有转录文件 (模型升级)")
            
            model = self.load_whisper_model()
            self.log(f"🎙️ 开始转录音频文件: {audio_file}")
            
            # 优化的转录参数 - 添加更好的分段控制
            transcribe_options = {
                'language': 'zh',  # 明确指定中文，避免语言检测时间
                'fp16': False,     # CPU下关闭fp16
                'task': 'transcribe',  # 明确指定任务类型
                'verbose': False,  # 减少冗余输出
                'word_timestamps': True,  # 启用词级时间戳，有助于更好的分段
                'condition_on_previous_text': True,  # 基于前文上下文，提高连贯性
            }
            
            # 如果是GPU，启用一些优化选项
            import torch
            if torch.cuda.is_available():
                transcribe_options['fp16'] = True  # GPU下启用fp16加速
                print("🚀 使用GPU加速转录...")
            else:
                print("💻 使用CPU转录...")
            
            result = model.transcribe(audio_file, **transcribe_options)
            original_segments = result.get('segments', [])
            print(f"✅ 转录完成，识别到 {len(original_segments)} 个原始语音片段")
            
            # 合并短片段以减少片段数量
            merged_segments = self.merge_short_segments(original_segments)
            print(f"📊 合并短片段后: {len(merged_segments)} 个片段")
            
            # 生成SRT格式字幕（使用合并后的片段）
            srt_content = self.generate_srt(merged_segments)
            
            # 确保transcripts目录存在
            os.makedirs('transcripts', exist_ok=True)
            
            # 保存SRT文件
            with open(srt_file, 'w', encoding='utf-8') as f:
                f.write(srt_content)
            
            # GPT字幕校正
            self.log("🔍 开始GPT字幕校正...")
            corrected_text = self.correct_transcript_with_gpt(result['text'])
            
            # 保存校正后的纯文本转录
            with open(transcript_file, 'w', encoding='utf-8') as f:
                f.write(corrected_text)
            
            print(f"✅ 转录完成，保存到: {srt_file}")
            
            return corrected_text, srt_file, merged_segments
            
        except Exception as e:
            raise Exception(f"语音转录失败: {str(e)}")
    
    def merge_short_segments(self, segments, target_duration=30.0, max_duration=60.0):
        """
        合并短片段以减少片段数量，提高分析效率
        保留原始片段信息以便更精确的时间戳匹配
        
        Args:
            segments: 原始片段列表
            target_duration: 目标片段时长（秒）
            max_duration: 最大片段时长（秒）
        """
        if not segments:
            return segments
        
        merged_segments = []
        current_segment = None
        current_original_segments = []  # 记录合并的原始片段
        
        for segment in segments:
            # 确保segment有正确的字段
            if not isinstance(segment, dict):
                continue
                
            start = segment.get('start', 0)
            end = segment.get('end', 0)
            text = segment.get('text', '').strip()
            
            if not text:  # 跳过空文本片段
                continue
            
            if current_segment is None:
                # 开始新的合并片段
                current_segment = {
                    'start': start,
                    'end': end,
                    'text': text,
                    'original_segments': [segment]  # 保留原始片段信息
                }
                current_original_segments = [segment]
            else:
                # 检查是否应该合并到当前片段
                current_duration = current_segment['end'] - current_segment['start']
                gap = start - current_segment['end']
                
                # 合并条件：
                # 1. 当前片段时长小于目标时长
                # 2. 时间间隔不超过3秒（避免合并不相关的内容）
                # 3. 合并后不超过最大时长
                if (current_duration < target_duration and 
                    gap <= 3.0 and 
                    (end - current_segment['start']) <= max_duration):
                    
                    # 合并到当前片段
                    current_segment['end'] = end
                    current_segment['text'] += ' ' + text
                    current_segment['original_segments'].append(segment)
                    current_original_segments.append(segment)
                else:
                    # 保存当前片段，开始新片段
                    merged_segments.append(current_segment)
                    current_segment = {
                        'start': start,
                        'end': end,
                        'text': text,
                        'original_segments': [segment]
                    }
                    current_original_segments = [segment]
        
        # 添加最后一个片段
        if current_segment is not None:
            merged_segments.append(current_segment)
        
        return merged_segments

    def parse_srt_file(self, srt_file):
        """解析SRT文件获取segments信息"""
        segments = []
        try:
            with open(srt_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 简单的SRT解析
            blocks = content.strip().split('\n\n')
            for block in blocks:
                lines = block.strip().split('\n')
                if len(lines) >= 3:
                    # 解析时间戳
                    time_line = lines[1]
                    if ' --> ' in time_line:
                        start_str, end_str = time_line.split(' --> ')
                        start_seconds = self.srt_time_to_seconds(start_str)
                        end_seconds = self.srt_time_to_seconds(end_str)
                        
                        # 合并文本行
                        text = ' '.join(lines[2:])
                        
                        segments.append({
                            'start': start_seconds,
                            'end': end_seconds,
                            'text': text
                        })
            
            return segments
        except Exception as e:
            print(f"解析SRT文件失败: {e}")
            return []
    
    def srt_time_to_seconds(self, time_str):
        """将SRT时间格式转换为秒数"""
        try:
            # 格式: HH:MM:SS,mmm
            time_part, ms_part = time_str.split(',')
            h, m, s = map(int, time_part.split(':'))
            ms = int(ms_part)
            return h * 3600 + m * 60 + s + ms / 1000.0
        except:
            return 0
    
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
            # 更准确的token估算 (中文: 1字符 ≈ 1.5 tokens, 英文: 1 token ≈ 4 characters)
            # 为中文内容使用更保守的估算
            estimated_tokens = len(transcript) * 1.5  # 中文字符更准确的token估算
            
            # GPT-4的实际限制：输入token约8192，需要预留输出空间
            # 提示词大约使用500-800 tokens，输出需要预留1000-1500 tokens
            max_input_tokens = 6000  # 保守估计，确保不超过GPT-4限制
            
            self.log(f"📊 文字稿长度: {len(transcript)} 字符")
            self.log(f"📊 估算token数: {estimated_tokens:.0f}")
            self.log(f"📊 模型限制: {max_input_tokens} tokens (包含提示词)")
            
            if estimated_tokens <= max_input_tokens:
                self.log("📝 文本长度适中，使用单次分析")
                return self._analyze_single_chunk(transcript, segments)
            else:
                self.log("📝 文本过长，使用分段分析")
                return self._analyze_multiple_chunks(transcript, segments, max_input_tokens)
            
        except Exception as e:
            raise Exception(f"内容分析失败: {str(e)}")

    def _format_segments_for_gpt(self, segments):
        """将segments格式化为带时间戳的文本，供GPT直接分析"""
        formatted_lines = []
        
        for segment in segments:
            start_time = segment.get('start', 0)
            text = segment.get('text', '').strip()
            
            if text:
                # 将秒数转换为 mm:ss 格式
                minutes = int(start_time // 60)
                seconds = int(start_time % 60)
                time_str = f"{minutes:02d}:{seconds:02d}"
                
                formatted_lines.append(f"[{time_str}] {text}")
        
        return '\n'.join(formatted_lines)

    def _analyze_single_chunk(self, transcript, segments):
        """分析单个文本块 - 重构版：基于带时间戳的字幕直接分析"""
        # 格式化segments为带时间戳的文本
        timestamped_content = self._format_segments_for_gpt(segments)
        
        prompt = f"""
请分析以下YouTube视频的带时间戳字幕，并生成一份简报。

带时间戳的字幕内容：
{timestamped_content}

请按以下格式输出JSON：
{{
    "summary": "视频主要内容的简洁总结（3-5句话）",
    "key_points": [
        {{
            "point": "要点描述",
            "explanation": "详细解释",
            "timestamp": 83,
            "quote": "原文引用"
        }}
    ]
}}

重要要求：
1. 提取3-8个关键要点，按时间顺序排列
2. timestamp字段必须填写准确的秒数（从字幕的时间戳中获取）
3. 如果是段落总结，使用该段落第一个字幕的时间戳
4. 如果引用了某句金句，使用该金句所在字幕的准确时间戳
5. 不同要点必须有不同的时间戳，体现内容的时间进展
6. quote字段包含相关的原文片段，但不用于匹配（时间戳已经准确）

示例时间戳格式：如果字幕显示[02:35]，则timestamp应该填写155（2分35秒=155秒）
"""

        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4",  # 确保使用正确的模型名称
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1500  # 限制输出token数量
            )
        except Exception as e:
            # 如果遇到token限制错误，尝试使用更大容量的模型
            if "token" in str(e).lower() or "context" in str(e).lower():
                self.log(f"⚠️ GPT-4 token限制，尝试使用gpt-4-turbo...")
                try:
                    response = self.openai_client.chat.completions.create(
                        model="gpt-4-turbo",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.3,
                        max_tokens=1500
                    )
                except Exception as e2:
                    # 如果还是失败，尝试缩短文本
                    self.log(f"⚠️ gpt-4-turbo也失败，缩短文本重试...")
                    shortened_transcript = transcript[:4000]  # 截取前4000字符
                    shortened_prompt = prompt.replace(transcript, shortened_transcript)
                    response = self.openai_client.chat.completions.create(
                        model="gpt-4",
                        messages=[{"role": "user", "content": shortened_prompt}],
                        temperature=0.3,
                        max_tokens=1500
                    )
            else:
                raise e
        
        # 添加GPT响应调试信息
        gpt_response = response.choices[0].message.content
        self.log(f"🤖 GPT响应内容长度: {len(gpt_response) if gpt_response else 0}")
        
        if not gpt_response or gpt_response.strip() == "":
            self.log("❌ GPT返回空响应")
            raise Exception("GPT返回空响应")
        
        # 打印前200个字符用于调试
        self.log(f"🔍 GPT响应前200字符: {gpt_response[:200]}")
        
        try:
            analysis_result = json.loads(gpt_response)
        except json.JSONDecodeError as e:
            self.log(f"❌ JSON解析失败: {str(e)}")
            self.log(f"🔍 GPT完整响应: {gpt_response}")
            
            # 尝试修复常见的JSON格式问题
            if gpt_response.startswith("```json"):
                # 移除代码块标记
                cleaned_response = gpt_response.replace("```json", "").replace("```", "").strip()
                self.log(f"🔧 尝试移除代码块标记")
                try:
                    analysis_result = json.loads(cleaned_response)
                    self.log(f"✅ 修复成功")
                except:
                    raise Exception(f"JSON解析失败，即使修复后也无法解析: {str(e)}")
            else:
                raise Exception(f"JSON解析失败: {str(e)}")
        
        # 新流程：GPT直接返回准确的时间戳，无需后续匹配
        # 验证时间戳的合理性
        if 'key_points' in analysis_result:
            for i, point in enumerate(analysis_result['key_points']):
                timestamp = point.get('timestamp', 0)
                # 确保时间戳是数字且合理
                if not isinstance(timestamp, (int, float)) or timestamp < 0:
                    self.log(f"⚠️ 要点{i+1}的时间戳无效: {timestamp}，设为0")
                    point['timestamp'] = 0
                else:
                    self.log(f"✅ 要点{i+1}时间戳: {timestamp}秒 ({int(timestamp//60):02d}:{int(timestamp%60):02d})")
        
        return analysis_result

    def _analyze_multiple_chunks(self, transcript, segments, max_input_tokens):
        """分段分析长文本"""
        # 转换token限制为字符数（中文字符）
        # 为分段预留一些token空间给提示词
        prompt_tokens = 500  # 预留给提示词的token
        available_tokens = max_input_tokens - prompt_tokens
        chunk_size_chars = int(available_tokens / 1.5)  # 转换为中文字符数
        
        chunks = []
        
        # 智能分割：先尝试句子边界，如果没有则按字符数强制分割
        # 尝试不同的分割方法
        potential_delimiters = ['。', '！', '？', '\n', ' ']
        best_sentences = None
        
        for delimiter in potential_delimiters:
            test_sentences = transcript.split(delimiter)
            if len(test_sentences) > 1:  # 找到有效分割
                best_sentences = test_sentences
                best_delimiter = delimiter
                break
        
        if best_sentences is None or len(best_sentences) == 1:
            # 没有找到合适的分隔符，按字符数强制分割
            best_sentences = []
            for i in range(0, len(transcript), chunk_size_chars):
                chunk = transcript[i:i + chunk_size_chars]
                best_sentences.append(chunk)
            best_delimiter = ""
        
        current_chunk = ""
        current_segments = []
        
        for i, sentence in enumerate(best_sentences):
            # 重新加上分隔符（除了最后一句和强制分割的情况）
            if best_delimiter and i < len(best_sentences) - 1:
                sentence_with_delimiter = sentence + best_delimiter
            else:
                sentence_with_delimiter = sentence
            
            # 检查添加这个句子是否会超过限制
            if len(current_chunk + sentence_with_delimiter) <= chunk_size_chars or not current_chunk:
                current_chunk += sentence_with_delimiter
                # 找到对应的segments
                chunk_segments = [s for s in segments if sentence[:20] in s.get('text', '')]
                current_segments.extend(chunk_segments)
            else:
                # 当前句子会导致超限，保存当前块并开始新块
                if current_chunk:  # 确保不保存空块
                    chunks.append((current_chunk, current_segments))
                
                # 检查单个句子是否太长
                if len(sentence_with_delimiter) > chunk_size_chars:
                    # 句子太长，按字符数强制分割
                    for j in range(0, len(sentence_with_delimiter), chunk_size_chars):
                        sub_chunk = sentence_with_delimiter[j:j + chunk_size_chars]
                        if sub_chunk:
                            chunks.append((sub_chunk, []))
                    current_chunk = ""
                    current_segments = []
                else:
                    current_chunk = sentence_with_delimiter
                    current_segments = [s for s in segments if sentence[:20] in s.get('text', '')]
        
        # 添加最后一个块
        if current_chunk:
            chunks.append((current_chunk, current_segments))
        
        self.log(f"📝 分割成 {len(chunks)} 个文本块进行分析")
        self.log(f"📝 每块最大字符数: {chunk_size_chars}")
        
        # 分析每个chunk
        all_summaries = []
        all_key_points = []
        
        for i, (chunk_text, chunk_segments) in enumerate(chunks):
            chunk_char_count = len(chunk_text)
            estimated_chunk_tokens = chunk_char_count * 1.5
            self.log(f"📊 分析第 {i+1}/{len(chunks)} 个文本块 ({chunk_char_count}字符, ~{estimated_chunk_tokens:.0f}tokens)...")
            
            try:
                chunk_analysis = self._analyze_chunk_with_context(chunk_text, i+1, len(chunks))
                
                if 'summary' in chunk_analysis:
                    all_summaries.append(chunk_analysis['summary'])
                if 'key_points' in chunk_analysis:
                    # 调整时间戳为原视频的相对时间
                    adjusted_points = []
                    for point in chunk_analysis['key_points']:
                        # 在原segments中找到匹配的时间戳
                        matching_segment = self._find_matching_segment(point.get('quote', ''), segments)
                        if matching_segment:
                            point['timestamp'] = matching_segment['start']
                        adjusted_points.append(point)
                    all_key_points.extend(adjusted_points)
            except Exception as e:
                self.log(f"⚠️ 第{i+1}块分析失败: {str(e)}")
                # 继续处理其他块
                continue
        
        # 合并所有分析结果
        self.log("📊 合并分析结果...")
        final_summary = self._merge_summaries(all_summaries)
        final_key_points = self._merge_key_points(all_key_points)
        
        return {
            'summary': final_summary,
            'key_points': final_key_points
        }

    def _analyze_chunk_with_context(self, chunk_text, chunk_index, total_chunks):
        """分析单个文本块（带上下文信息）"""
        prompt = f"""
请分析以下YouTube视频的部分文字稿（第{chunk_index}部分，共{total_chunks}部分）：

文字稿内容：
{chunk_text}

请按以下格式输出JSON：
{{
    "summary": "这部分内容的简洁总结（2-3句话）",
    "key_points": [
        {{
            "point": "要点描述",
            "explanation": "详细解释",
            "timestamp": 0,
            "quote": "原文引用（如果有的话）"
        }}
    ]
}}

要求：
1. 提取2-4个关键要点
2. 重点关注这部分的主要观点
3. 提供原文引用以便后续匹配时间戳
"""

        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1200  # 分块分析使用较少的输出token
            )
        except Exception as e:
            if "token" in str(e).lower() or "context" in str(e).lower():
                # 如果chunk仍然太大，进一步缩短
                shortened_chunk = chunk_text[:2000]
                shortened_prompt = prompt.replace(chunk_text, shortened_chunk)
                response = self.openai_client.chat.completions.create(
                    model="gpt-4",
                    messages=[{"role": "user", "content": shortened_prompt}],
                    temperature=0.3,
                    max_tokens=1200
                )
            else:
                raise e
        
        return json.loads(response.choices[0].message.content)

    def _find_matching_segment(self, quote_text, segments):
        """在segments中找到匹配的文本片段，使用改进的匹配算法"""
        if not quote_text or not segments:
            return None
        
        # 清理引用文本
        quote_clean = self._clean_text_for_matching(quote_text)
        if not quote_clean:
            return None
        
        best_match = None
        best_score = 0
        
        # 首先尝试精确子字符串匹配（不区分大小写和标点）
        for segment in segments:
            segment_text = segment.get('text', '').lower()
            quote_lower = quote_text.lower()
            
            # 移除标点符号进行匹配
            import re
            segment_clean_simple = re.sub(r'[^\w\s]', '', segment_text)
            quote_clean_simple = re.sub(r'[^\w\s]', '', quote_lower)
            
            # 检查是否有足够长的共同子字符串
            if len(quote_clean_simple) > 10:  # 引用足够长
                if quote_clean_simple in segment_clean_simple or segment_clean_simple in quote_clean_simple:
                    self.log(f"🎯 时间戳匹配: 找到子字符串精确匹配")
                    return segment
        
        # 如果没有精确匹配，尝试分词匹配
        quote_words = quote_clean.split()
        if len(quote_words) >= 3:  # 至少3个词才进行匹配
            for segment in segments:
                # 优先在合并片段的原始片段中查找更精确的匹配
                if 'original_segments' in segment and segment['original_segments']:
                    for orig_segment in segment['original_segments']:
                        orig_clean = self._clean_text_for_matching(orig_segment.get('text', ''))
                        if orig_clean:
                            score = self._calculate_word_overlap(quote_words, orig_clean.split())
                            if score > best_score:
                                best_score = score
                                best_match = orig_segment
                
                # 也检查合并后的片段
                segment_clean = self._clean_text_for_matching(segment.get('text', ''))
                if segment_clean:
                    score = self._calculate_word_overlap(quote_words, segment_clean.split())
                    if score > best_score:
                        best_score = score
                        best_match = segment
        
            # 降低匹配阈值，因为分词匹配更可靠
            if best_score >= 0.2:  # 20%的词汇重叠阈值（从40%降低）
                self.log(f"🎯 时间戳匹配: 找到{best_score:.2f}词汇重叠匹配")
                return best_match
        
        # 最后尝试部分匹配
        partial_match = self._find_partial_match(quote_clean, segments)
        if partial_match:
            self.log(f"⚠️ 时间戳匹配: 使用部分匹配")
            return partial_match
        
        # 最后的回退选项 - 智能位置估算
        if segments:
            # 改进的启发式：根据引用文本在完整转录中的位置估算时间戳
            estimated_position = self._estimate_quote_position(quote_text, segments)
            if estimated_position is not None:
                self.log(f"📍 时间戳匹配: 使用位置估算匹配")
                return estimated_position
            
            # 智能回退策略：不总是使用第一个片段
            fallback_segment = self._get_fallback_segment(segments)
            self.log(f"❌ 时间戳匹配: 未找到匹配，使用智能回退策略")
            return fallback_segment
        
        return None
    
    def _calculate_word_overlap(self, words1, words2):
        """计算两个词列表的重叠率"""
        if not words1 or not words2:
            return 0
        
        set1 = set(words1)
        set2 = set(words2)
        
        intersection = len(set1.intersection(set2))
        union = len(set1.union(set2))
        
        return intersection / union if union > 0 else 0
    
    def _estimate_quote_position(self, quote_text, segments):
        """根据引用文本估算在segments中的位置 - 改进版本"""
        if not quote_text or not segments:
            return None
        
        # 构建完整文本和位置映射
        full_text_parts = []
        segment_boundaries = []  # 记录每个segment在完整文本中的边界
        
        current_pos = 0
        for i, seg in enumerate(segments):
            seg_text = seg.get('text', '')
            full_text_parts.append(seg_text)
            segment_boundaries.append((current_pos, current_pos + len(seg_text), i))
            current_pos += len(seg_text) + 1  # +1 for space
        
        full_text = ' '.join(full_text_parts)
        
        # 查找引用在完整文本中的大致位置
        quote_clean = quote_text.lower()
        full_text_clean = full_text.lower()
        
        # 尝试找到引用的关键词在全文中的位置
        quote_words = [w for w in quote_clean.split() if len(w) > 2][:8]  # 取前8个有意义的词
        
        if not quote_words:
            return self._get_fallback_segment(segments)
        
        best_segment = None
        max_score = 0
        
        # 为每个segment计算匹配分数
        for start_pos, end_pos, seg_idx in segment_boundaries:
            if seg_idx >= len(segments):
                continue
                
            # 扩展窗口：包含当前segment及其周围的文本
            window_start = max(0, start_pos - 100)
            window_end = min(len(full_text_clean), end_pos + 100)
            window_text = full_text_clean[window_start:window_end]
            
            # 计算匹配分数
            word_score = sum(1 for word in quote_words if word in window_text)
            
            # 归一化分数
            normalized_score = word_score / len(quote_words) if quote_words else 0
            
            if normalized_score > max_score:
                max_score = normalized_score
                best_segment = segments[seg_idx]
        
        if best_segment and max_score >= 0.25:  # 至少25%的关键词匹配
            self.log(f"📍 位置估算: 找到 {max_score:.2f} 匹配分数")
            return best_segment
        
        # 最后的回退策略
        return self._get_fallback_segment(segments)
    
    def correct_transcript_with_gpt(self, transcript_text):
        """使用GPT检查和校正转录文本中的同音字错误"""
        try:
            self.log("🔍 开始GPT字幕校正...")
            
            # 将长文本分段处理，避免token限制
            max_chars_per_chunk = 2000  # 每段最大字符数
            chunks = []
            
            # 按句子分割，保持语义完整性
            sentences = transcript_text.split('。')
            current_chunk = ""
            
            for sentence in sentences:
                if len(current_chunk + sentence + '。') <= max_chars_per_chunk:
                    current_chunk += sentence + '。'
                else:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    current_chunk = sentence + '。'
            
            if current_chunk:
                chunks.append(current_chunk.strip())
            
            corrected_chunks = []
            
            for i, chunk in enumerate(chunks):
                self.log(f"📝 校正第 {i+1}/{len(chunks)} 段文本...")
                
                prompt = f"""
请检查以下中文转录文本中的同音字错误，只替换明显错误的同音字，保持原意不变：

原文：
{chunk}

要求：
1. 只纠正明显的同音字错误（如：在->再，的->得，和->合等）
2. 不要改变句子结构和语义
3. 不要添加标点符号
4. 保持原文的语言风格
5. 如果不确定是否有错误，保持原文不变
6. 直接返回校正后的文本，不要添加说明

校正后的文本：
"""
                
                try:
                    response = self.openai_client.chat.completions.create(
                        model="gpt-4",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.1,  # 低温度保证一致性
                        max_tokens=800
                    )
                    
                    corrected_text = response.choices[0].message.content.strip()
                    corrected_chunks.append(corrected_text)
                    
                    # 记录修改情况
                    if corrected_text != chunk:
                        self.log(f"✏️ 段落 {i+1} 已校正")
                    else:
                        self.log(f"✅ 段落 {i+1} 无需校正")
                        
                except Exception as e:
                    self.log(f"⚠️ 段落 {i+1} 校正失败: {str(e)}，保持原文")
                    corrected_chunks.append(chunk)
            
            # 合并校正后的文本
            corrected_transcript = ' '.join(corrected_chunks)
            self.log("✅ GPT字幕校正完成")
            
            return corrected_transcript
            
        except Exception as e:
            self.log(f"❌ GPT字幕校正失败: {str(e)}，使用原始转录")
            return transcript_text
    
    def _clean_text_for_matching(self, text):
        """清理文本用于匹配"""
        if not text:
            return ""
        
        import re
        # 移除标点符号和多余空格，转换为小写
        cleaned = re.sub(r'[^\w\s]', '', text.lower())
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return cleaned
    
    def _calculate_text_similarity(self, text1, text2):
        """计算两个文本的相似度"""
        if not text1 or not text2:
            return 0
        
        # 使用简单的词汇重叠算法
        words1 = set(text1.split())
        words2 = set(text2.split())
        
        if not words1 or not words2:
            return 0
        
        # 计算Jaccard相似度
        intersection = words1 & words2
        union = words1 | words2
        
        if not union:
            return 0
        
        return len(intersection) / len(union)
    
    def _find_partial_match(self, quote_clean, segments):
        """寻找部分匹配的段落 - 使用基于词汇重叠度的智能匹配"""
        quote_words = quote_clean.split()
        if len(quote_words) < 3:  # 太短的引用不进行部分匹配
            return self._get_fallback_segment(segments)
        
        best_match = None
        best_score = 0
        
        # 为每个段落计算匹配分数
        for segment in segments:
            segment_clean = self._clean_text_for_matching(segment.get('text', ''))
            if not segment_clean:
                continue
                
            segment_words = segment_clean.split()
            
            # 计算词汇重叠度
            overlap_score = self._calculate_word_overlap(quote_words, segment_words)
            
            # 额外奖励：检查开头和结尾的匹配
            if self._has_partial_overlap(quote_words, segment_words):
                overlap_score += 0.2  # 给部分匹配额外分数
            
            if overlap_score > best_score:
                best_score = overlap_score
                best_match = segment
        
        # 如果有合理的匹配，返回最佳匹配
        if best_match and best_score >= 0.15:  # 降低阈值到15%
            self.log(f"📍 部分匹配: 找到 {best_score:.2f} 分数匹配")
            return best_match
        
        # 没有好的匹配，使用智能回退策略
        return self._get_fallback_segment(segments)
    
    def _has_partial_overlap(self, words1, words2):
        """检查两个词汇列表是否有部分重叠"""
        if len(words1) < 3 or len(words2) < 3:
            return False
        
        # 检查开头3个词的匹配
        start_match = len(set(words1[:3]) & set(words2[:3])) >= 2
        
        # 检查结尾3个词的匹配  
        end_match = len(set(words1[-3:]) & set(words2[-3:])) >= 2
        
        return start_match or end_match

    def _get_fallback_segment(self, segments):
        """智能回退策略 - 避免总是使用第一个片段（start=0）"""
        if not segments:
            return None
            
        # 过滤掉开始时间为0的片段（除非它们是唯一选择）
        non_zero_segments = [seg for seg in segments if seg.get('start', 0) > 0]
        
        if non_zero_segments:
            # 返回中间位置的片段，而不是第一个
            middle_index = len(non_zero_segments) // 2
            selected_segment = non_zero_segments[middle_index]
            self.log(f"🔄 智能回退: 选择中间片段 (start={selected_segment.get('start', 0)})")
            return selected_segment
        
        # 如果所有片段都是start=0，或者没有其他选择，返回第一个
        if segments:
            self.log(f"⚠️ 智能回退: 使用第一个片段 (start={segments[0].get('start', 0)})")
            return segments[0]
        
        return None

    def _srt_time_to_seconds(self, time_str):
        """将SRT时间格式转换为秒数"""
        # 格式：00:01:23,456 -> 83.456
        time_part, milliseconds = time_str.split(',')
        hours, minutes, seconds = map(int, time_part.split(':'))
        total_seconds = hours * 3600 + minutes * 60 + seconds + int(milliseconds) / 1000
        return total_seconds

    def _merge_summaries(self, summaries):
        """合并多个摘要"""
        if not summaries:
            return "无法生成摘要"
        
        # 简单合并，实际项目中可以用AI再次总结
        combined = "。".join(summaries)
        return combined

    def _merge_key_points(self, all_key_points):
        """合并并去重关键要点"""
        # 简单去重和限制数量
        seen_points = set()
        merged_points = []
        
        for point in all_key_points:
            point_key = point.get('point', '')
            if point_key not in seen_points and len(merged_points) < 8:
                seen_points.add(point_key)
                merged_points.append(point)
        
        return merged_points
    
    def generate_report_html(self, video_title, youtube_url, analysis, srt_file):
        """生成HTML简报"""
        try:
            # 提取YouTube视频ID
            video_id = self.extract_video_id(youtube_url)
            
            # 读取并解析SRT字幕数据
            subtitles_data = []
            if os.path.exists(srt_file):
                with open(srt_file, 'r', encoding='utf-8') as f:
                    srt_content = f.read()
                
                # 解析SRT格式
                import re
                pattern = r'(\d+)\s*\n(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*\n(.*?)(?=\n\d+\s*\n|\Z)'
                matches = re.findall(pattern, srt_content, re.DOTALL)
                
                for match in matches:
                    subtitle_id, start_time, end_time, text = match
                    # 将时间转换为秒数
                    start_seconds = self._srt_time_to_seconds(start_time)
                    end_seconds = self._srt_time_to_seconds(end_time)
                    
                    subtitles_data.append({
                        'id': int(subtitle_id),
                        'start': start_seconds,
                        'end': end_seconds,
                        'text': text.strip().replace('\n', ' ')
                    })
            
            # 将字幕数据转换为JSON字符串，供JavaScript使用
            import json
            subtitles_json = json.dumps(subtitles_data, ensure_ascii=False)
            html_content = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{video_title} - 视频简报</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{ 
            font-family: Arial, sans-serif; 
            margin: 0; 
            padding: 0; 
            line-height: 1.6; 
            background-color: #f8f9fa;
        }}
        
        .container {{ 
            max-width: 1400px; 
            margin: 0 auto; 
            padding: 20px; 
        }}
        
        .header {{ 
            background: #fff; 
            padding: 20px; 
            border-radius: 8px; 
            margin-bottom: 20px; 
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        
        .main-content {{ 
            display: grid; 
            grid-template-columns: 1fr 1fr; 
            gap: 20px; 
            min-height: 70vh; 
        }}
        
        .left-panel {{ 
            display: flex; 
            flex-direction: column; 
            gap: 20px; 
        }}
        
        .video-container {{ 
            background: #fff; 
            border-radius: 8px; 
            padding: 15px; 
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            position: sticky;
            top: 20px;
        }}
        
        .video-wrapper {{ 
            position: relative; 
            padding-bottom: 56.25%; 
            height: 0; 
            overflow: hidden; 
            border-radius: 8px; 
        }}
        
        .video-wrapper iframe {{ 
            position: absolute; 
            top: 0; 
            left: 0; 
            width: 100%; 
            height: 100%; 
        }}
        
        .summary {{ 
            background: #e3f2fd; 
            padding: 20px; 
            border-radius: 8px; 
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        
        .right-panel {{ 
            display: flex; 
            flex-direction: column; 
            gap: 20px; 
        }}
        
        .key-points {{ 
            background: #fff; 
            padding: 20px; 
            border-radius: 8px; 
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        
        .key-point {{ 
            background: #f8f9fa; 
            border: 1px solid #e9ecef; 
            padding: 15px; 
            margin-bottom: 15px; 
            border-radius: 8px; 
            transition: transform 0.2s ease;
        }}
        
        .key-point:hover {{ 
            transform: translateY(-2px); 
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        }}
        
        .timestamp {{ 
            background: #007bff; 
            color: white; 
            padding: 6px 12px; 
            border-radius: 20px; 
            text-decoration: none; 
            cursor: pointer; 
            font-size: 0.9em;
            font-weight: 500;
            transition: all 0.2s ease;
        }}
        
        .timestamp:hover {{ 
            background: #0056b3; 
            transform: scale(1.05);
        }}
        
        .quote {{ 
            font-style: italic; 
            color: #6c757d; 
            margin-top: 10px; 
            padding: 10px; 
            background: #f1f3f4; 
            border-left: 4px solid #007bff; 
            border-radius: 4px;
        }}
        
        .subtitles-section {{ 
            background: #fff; 
            border-radius: 8px; 
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            overflow: hidden;
        }}
        
        .subtitle-toggle {{ 
            background: #28a745; 
            color: white; 
            border: none; 
            padding: 15px 20px; 
            width: 100%;
            cursor: pointer; 
            font-size: 16px;
            font-weight: 500;
            transition: background-color 0.2s ease;
        }}
        
        .subtitle-toggle:hover {{ 
            background: #218838; 
        }}
        
        .subtitles-container {{ 
            display: none; 
            max-height: 500px; 
            overflow-y: auto; 
            padding: 0;
        }}
        
        .subtitle-line {{ 
            padding: 12px 20px; 
            border-bottom: 1px solid #e9ecef;
            cursor: pointer; 
            transition: all 0.2s ease;
            position: relative;
            border-radius: 4px;
            margin: 2px 0;
        }}
        
        .subtitle-line:hover {{ 
            background: #e3f2fd; 
            transform: translateX(5px);
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        
        .subtitle-line.active {{ 
            background: #fff3cd; 
            border-left: 4px solid #ffc107;
            font-weight: 500;
            animation: highlight 0.5s ease-in-out;
        }}
        
        .subtitle-line.clicked {{
            background: #d1ecf1;
            transform: scale(1.02);
            border-left: 4px solid #17a2b8;
        }}
        
        @keyframes highlight {{
            0% {{ background: #ffecb3; }}
            100% {{ background: #fff3cd; }}
        }}
        
        @keyframes clickFeedback {{
            0% {{ transform: scale(1); }}
            50% {{ transform: scale(1.05); }}
            100% {{ transform: scale(1.02); }}
        }}
        
        .subtitle-time {{ 
            color: #007bff; 
            font-weight: bold; 
            margin-right: 15px; 
            font-size: 0.9em;
            display: inline-block;
            min-width: 60px;
        }}
        
        .subtitle-text {{ 
            color: #333; 
        }}
        
        /* 响应式设计 */
        @media (max-width: 1024px) {{
            .main-content {{ 
                grid-template-columns: 1fr; 
            }}
            
            .video-container {{
                position: relative;
                top: auto;
            }}
        }}
        
        @media (max-width: 768px) {{
            .container {{ 
                padding: 10px; 
            }}
            
            .header {{ 
                padding: 15px; 
            }}
            
            .main-content {{ 
                gap: 15px; 
            }}
            
            .key-point, .summary {{ 
                padding: 15px; 
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{video_title}</h1>
            <p><strong>原视频链接：</strong> <a href="{youtube_url}" target="_blank">{youtube_url}</a></p>
            <p><strong>生成时间：</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
        
        <div class="main-content">
            <div class="left-panel">
                <div class="video-container">
                    <div class="video-wrapper">
                        <div id="youtube-player"></div>
                    </div>
                </div>
                
                <div class="summary">
                    <h2>📋 内容摘要</h2>
                    <p>{analysis['summary']}</p>
                </div>
            </div>
            
            <div class="right-panel">
                <div class="key-points">
                    <h2>🔑 关键要点</h2>
"""
            
            for i, point in enumerate(analysis['key_points'], 1):
                timestamp_seconds = point.get('timestamp', 0)
                # 确保timestamp是数字类型
                try:
                    timestamp_seconds = float(timestamp_seconds) if timestamp_seconds else 0
                except (ValueError, TypeError):
                    timestamp_seconds = 0
                
                timestamp_display = self.seconds_to_display_time(timestamp_seconds)
                
                html_content += f"""
        <div class="key-point">
            <h3>{i}. {point['point']}</h3>
            <p>{point['explanation']}</p>
            <p><span class="timestamp" onclick="seekToTime({int(timestamp_seconds)})">⏰ {timestamp_display}</span></p>
            {f'<div class="quote">"{point["quote"]}"</div>' if point.get('quote') else ''}
        </div>
"""
            
            html_content += f"""
                </div>
                
                <div class="subtitles-section">
                    <button class="subtitle-toggle" onclick="toggleSubtitles()">
                        📝 展开完整字幕
                    </button>
                    
                    <div class="subtitles-container" id="subtitles-container">
                        <div id="subtitles-list">
                            <!-- 字幕内容将由JavaScript动态生成 -->
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- YouTube Player API -->
    <script src="https://www.youtube.com/iframe_api"></script>
    <script>
        let player;
        let subtitlesData = {subtitles_json};
        let currentHighlightedSubtitle = null;
        let progressUpdateTimer = null;
        
        // YouTube Player API回调
        function onYouTubeIframeAPIReady() {{
            player = new YT.Player('youtube-player', {{
                height: '100%',
                width: '100%',
                videoId: '{video_id}',
                playerVars: {{
                    'autoplay': 0,
                    'controls': 1,
                    'rel': 0,
                    'showinfo': 0,
                    'modestbranding': 1
                }},
                events: {{
                    'onReady': onPlayerReady,
                    'onStateChange': onPlayerStateChange
                }}
            }});
        }}
        
        function onPlayerReady(event) {{
            console.log('YouTube player ready');
            generateSubtitlesList();
        }}
        
        function onPlayerStateChange(event) {{
            // 当视频播放时开始监听进度
            if (event.data === YT.PlayerState.PLAYING) {{
                startProgressMonitoring();
            }} else {{
                stopProgressMonitoring();
            }}
        }}
        
        // 开始监听播放进度
        function startProgressMonitoring() {{
            if (progressUpdateTimer) {{
                clearInterval(progressUpdateTimer);
            }}
            
            progressUpdateTimer = setInterval(() => {{
                if (player && player.getCurrentTime) {{
                    const currentTime = player.getCurrentTime();
                    updateSubtitleHighlight(currentTime);
                }}
            }}, 500); // 每500ms更新一次
        }}
        
        // 停止监听播放进度
        function stopProgressMonitoring() {{
            if (progressUpdateTimer) {{
                clearInterval(progressUpdateTimer);
                progressUpdateTimer = null;
            }}
        }}
        
        // 更新字幕高亮 - 优化版本
        function updateSubtitleHighlight(currentTime) {{
            // 性能优化：使用二分查找找到当前字幕
            const currentSubtitle = findCurrentSubtitle(currentTime);
            
            if (currentSubtitle && currentSubtitle !== currentHighlightedSubtitle) {{
                // 移除之前的高亮
                if (currentHighlightedSubtitle) {{
                    const prevElement = document.querySelector(`[data-subtitle-id="${{currentHighlightedSubtitle.id}}"]`);
                    if (prevElement) {{
                        prevElement.classList.remove('active');
                    }}
                }}
                
                // 添加新的高亮
                const currentElement = document.querySelector(`[data-subtitle-id="${{currentSubtitle.id}}"]`);
                if (currentElement) {{
                    currentElement.classList.add('active');
                    
                    // 自动滚动到当前字幕（仅在字幕面板展开时）
                    const container = document.getElementById('subtitles-container');
                    if (container && container.style.display !== 'none') {{
                        // 节流滚动以提升性能
                        if (!currentElement.isScrolling) {{
                            currentElement.isScrolling = true;
                            currentElement.scrollIntoView({{
                                behavior: 'smooth',
                                block: 'center'
                            }});
                            setTimeout(() => {{
                                currentElement.isScrolling = false;
                            }}, 1000);
                        }}
                    }}
                }}
                
                currentHighlightedSubtitle = currentSubtitle;
            }}
        }}
        
        // 优化的字幕查找函数 - 使用缓存提升性能
        let lastSearchIndex = 0;
        function findCurrentSubtitle(currentTime) {{
            // 从上次位置开始搜索，减少查找时间
            for (let i = lastSearchIndex; i < subtitlesData.length; i++) {{
                const subtitle = subtitlesData[i];
                if (currentTime >= subtitle.start && currentTime <= subtitle.end) {{
                    lastSearchIndex = Math.max(0, i - 1); // 缓存位置
                    return subtitle;
                }}
                if (currentTime < subtitle.start) {{
                    break; // 当前时间已过，无需继续查找
                }}
            }}
            
            // 如果没找到，从头开始查找一次
            for (let i = 0; i < lastSearchIndex; i++) {{
                const subtitle = subtitlesData[i];
                if (currentTime >= subtitle.start && currentTime <= subtitle.end) {{
                    lastSearchIndex = Math.max(0, i - 1);
                    return subtitle;
                }}
            }}
            
            return null;
        }}
        
        // 跳转到指定时间
        function seekToTime(seconds, clickedElement = null) {{
            if (player && player.seekTo) {{
                player.seekTo(seconds, true);
                player.playVideo();
                
                // 添加点击反馈效果
                if (clickedElement) {{
                    // 移除所有clicked类
                    document.querySelectorAll('.subtitle-line.clicked').forEach(el => {{
                        el.classList.remove('clicked');
                    }});
                    
                    // 添加点击效果
                    clickedElement.classList.add('clicked');
                    clickedElement.style.animation = 'clickFeedback 0.3s ease-in-out';
                    
                    // 延迟移除点击效果
                    setTimeout(() => {{
                        clickedElement.style.animation = '';
                    }}, 300);
                }}
                
                // 确保字幕面板是展开的
                const container = document.getElementById('subtitles-container');
                if (container.style.display === 'none' || container.style.display === '') {{
                    toggleSubtitles();
                }}
                
                // 延迟一下再滚动到对应字幕
                setTimeout(() => {{
                    const targetElement = document.querySelector(`[data-start="${{seconds}}"]`);
                    if (targetElement) {{
                        targetElement.scrollIntoView({{
                            behavior: 'smooth',
                            block: 'center'
                        }});
                    }}
                }}, 300);
            }}
        }}
        
        // 切换字幕显示
        function toggleSubtitles() {{
            const container = document.getElementById('subtitles-container');
            const button = document.querySelector('.subtitle-toggle');
            
            if (container.style.display === 'none' || container.style.display === '') {{
                container.style.display = 'block';
                button.textContent = '📝 收起字幕';
            }} else {{
                container.style.display = 'none';
                button.textContent = '📝 展开完整字幕';
            }}
        }}
        
        // 生成字幕列表
        function generateSubtitlesList() {{
            const subtitlesList = document.getElementById('subtitles-list');
            
            subtitlesData.forEach(subtitle => {{
                const subtitleDiv = document.createElement('div');
                subtitleDiv.className = 'subtitle-line';
                subtitleDiv.setAttribute('data-subtitle-id', subtitle.id);
                subtitleDiv.setAttribute('data-start', subtitle.start);
                subtitleDiv.onclick = (event) => {{
                    event.preventDefault();
                    seekToTime(subtitle.start, subtitleDiv);
                }};
                
                const timeSpan = document.createElement('span');
                timeSpan.className = 'subtitle-time';
                timeSpan.textContent = formatTime(subtitle.start);
                
                const textSpan = document.createElement('span');
                textSpan.className = 'subtitle-text';
                textSpan.textContent = subtitle.text;
                
                subtitleDiv.appendChild(timeSpan);
                subtitleDiv.appendChild(textSpan);
                subtitlesList.appendChild(subtitleDiv);
            }});
        }}
        
        // 格式化时间显示
        function formatTime(seconds) {{
            const minutes = Math.floor(seconds / 60);
            const secs = Math.floor(seconds % 60);
            return minutes.toString().padStart(2, '0') + ':' + secs.toString().padStart(2, '0');
        }}
        
        // 添加键盘快捷键支持
        document.addEventListener('keydown', (event) => {{
            if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA') {{
                return; // 如果在输入框中，不处理快捷键
            }}
            
            switch(event.key) {{
                case ' ': // 空格键播放/暂停
                    event.preventDefault();
                    if (player && player.getPlayerState && player.playVideo && player.pauseVideo) {{
                        const state = player.getPlayerState();
                        if (state === YT.PlayerState.PLAYING) {{
                            player.pauseVideo();
                        }} else {{
                            player.playVideo();
                        }}
                    }}
                    break;
                case 's': // S键切换字幕
                case 'S':
                    event.preventDefault();
                    toggleSubtitles();
                    break;
                case 'ArrowLeft': // 左箭头后退10秒
                    event.preventDefault();
                    if (player && player.seekTo && player.getCurrentTime) {{
                        const currentTime = player.getCurrentTime();
                        player.seekTo(Math.max(0, currentTime - 10), true);
                    }}
                    break;
                case 'ArrowRight': // 右箭头前进10秒
                    event.preventDefault();
                    if (player && player.seekTo && player.getCurrentTime) {{
                        const currentTime = player.getCurrentTime();
                        player.seekTo(currentTime + 10, true);
                    }}
                    break;
            }}
        }});
        
        // 添加触屏设备支持
        let touchStartY = 0;
        document.addEventListener('touchstart', (event) => {{
            touchStartY = event.touches[0].clientY;
        }});
        
        document.addEventListener('touchend', (event) => {{
            const touchEndY = event.changedTouches[0].clientY;
            const diff = touchStartY - touchEndY;
            
            // 上滑手势展开字幕
            if (diff > 50) {{
                const container = document.getElementById('subtitles-container');
                if (container.style.display === 'none' || container.style.display === '') {{
                    toggleSubtitles();
                }}
            }}
        }});
        
        // 页面卸载时清理定时器
        window.addEventListener('beforeunload', () => {{
            stopProgressMonitoring();
        }});
        
        // 页面可见性变化时的优化
        document.addEventListener('visibilitychange', () => {{
            if (document.hidden) {{
                // 页面隐藏时减少更新频率
                if (progressUpdateTimer) {{
                    clearInterval(progressUpdateTimer);
                    progressUpdateTimer = setInterval(() => {{
                        if (player && player.getCurrentTime) {{
                            const currentTime = player.getCurrentTime();
                            updateSubtitleHighlight(currentTime);
                        }}
                    }}, 2000); // 2秒更新一次
                }}
            }} else {{
                // 页面可见时恢复正常频率
                if (player && player.getPlayerState && player.getPlayerState() === YT.PlayerState.PLAYING) {{
                    startProgressMonitoring();
                }}
            }}
        }});
    </script>
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
        # 确保输入是数字类型
        try:
            seconds = float(seconds) if seconds else 0
        except (ValueError, TypeError):
            seconds = 0
            
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes:02d}:{secs:02d}"
    
    def process_video(self, video_id, youtube_url):
        """完整的视频处理流程，支持检查点恢复"""
        self.clear_logs()  # 清除之前的日志
        
        self.log("="*60)
        self.log("🎬 开始视频处理流程")
        self.log(f"📹 视频ID: {video_id}")
        self.log(f"🔗 YouTube URL: {youtube_url}")
        self.log("="*60)
        
        try:
            # 检查当前状态和下一个检查点
            next_checkpoint = self.get_next_checkpoint(video_id)
            if next_checkpoint is None:
                self.log("🎉 所有检查点已完成，无需处理")
                return
            
            self.log(f"📍 从检查点开始: {next_checkpoint}")
            self.log("📝 更新数据库状态为processing...")
            self.db.update_video_status(video_id, 'processing')
            self.log("✅ 数据库状态更新完成")
            
            # 根据检查点恢复处理
            audio_file = None
            video_title = None
            transcript = None
            srt_file = None
            segments = None
            
            if next_checkpoint == Checkpoint.DOWNLOAD:
                # 1. 下载音频
                self.log("1️⃣ 检查点: 下载YouTube音频")
                audio_file, video_title = self.download_audio(youtube_url, video_id)
                self.log(f"✅ 音频下载完成: {audio_file}")
                
                # 更新下载检查点
                self.db.update_checkpoint(video_id, Checkpoint.DOWNLOAD, CheckpointStatus.COMPLETED, audio_file)
                next_checkpoint = Checkpoint.TRANSCRIBE
            
            if next_checkpoint == Checkpoint.TRANSCRIBE:
                # 获取音频文件（如果没有下载）
                if not audio_file:
                    checkpoint_status = self.db.get_checkpoint_status(video_id)
                    audio_file = checkpoint_status['audio_file_path']
                    if not audio_file or not os.path.exists(audio_file):
                        raise Exception("音频文件不存在，需要重新下载")
                
                # 2. 模型检查和智能重分析
                self.log("2️⃣ 检查点: 检查Whisper模型和重分析需求")
                current_model = self.get_current_optimal_model()
                should_reanalyze, previous_model = self.should_reanalyze_with_better_model(video_id, current_model)
                
                if should_reanalyze:
                    self.log(f"🚀 将使用更好的模型重新分析")
                    self.log(f"📊 质量提升预期: 转录准确度 +10-15%")
                    force_retranscribe = True
                else:
                    self.log(f"📝 使用模型: {current_model}")
                    force_retranscribe = False
                
                # 3. 语音转录
                self.log("3️⃣ 检查点: 使用Whisper进行语音转录")
                transcript, srt_file, segments = self.transcribe_audio(audio_file, force_retranscribe)
                self.log(f"✅ 语音转录完成，共{len(segments)}个片段")
                
                # 更新使用的模型记录和转录检查点
                self.db.update_whisper_model(video_id, current_model)
                self.db.update_checkpoint(video_id, Checkpoint.TRANSCRIBE, CheckpointStatus.COMPLETED, srt_file)
                next_checkpoint = Checkpoint.REPORT
            
            if next_checkpoint == Checkpoint.REPORT:
                # 获取转录文件（如果没有转录）
                if not transcript or not srt_file:
                    checkpoint_status = self.db.get_checkpoint_status(video_id)
                    srt_file = checkpoint_status['transcript_file_path']
                    if not srt_file or not os.path.exists(srt_file):
                        raise Exception("转录文件不存在，需要重新转录")
                    
                    # 读取转录文件
                    txt_file = srt_file.replace('.srt', '.txt')
                    if os.path.exists(txt_file):
                        with open(txt_file, 'r', encoding='utf-8') as f:
                            transcript = f.read()
                    else:
                        raise Exception("转录文本文件不存在")
                    
                    # 重新解析segments（简化版）
                    segments = []
                
                # 获取视频标题（如果需要）
                if not video_title:
                    try:
                        # 尝试从数据库获取
                        with self.db.get_connection() as conn:
                            cursor = conn.cursor()
                            cursor.execute('SELECT video_title FROM videos WHERE id=?', (video_id,))
                            result = cursor.fetchone()
                            if result and result[0]:
                                video_title = result[0]
                            else:
                                # 从YouTube URL重新获取
                                video_title = self.extract_video_title(youtube_url)
                    except:
                        video_title = "未知标题"
                
                # 4. AI分析
                self.log("4️⃣ 检查点: 使用GPT-4进行内容分析")
                analysis = self.analyze_content(transcript, segments)
                self.log(f"✅ 内容分析完成，提取{len(analysis.get('key_points', []))}个关键要点")
                
                # 5. 生成简报
                self.log("5️⃣ 检查点: 生成HTML简报")
                report_filename = self.generate_report_html(video_title, youtube_url, analysis, srt_file)
                self.log(f"✅ HTML简报生成完成: {report_filename}")
                
                # 更新简报检查点和数据库
                self.db.update_checkpoint(video_id, Checkpoint.REPORT, CheckpointStatus.COMPLETED)
                self.db.update_report_filename(video_id, report_filename)
            
            # 最终状态更新
            self.log("📝 更新最终状态...")
            self.db.update_video_status(video_id, 'completed')
            
            self.log("="*60)
            self.log("🎉 视频处理流程全部完成!")
            if 'report_filename' in locals():
                self.log(f"📋 简报文件: {report_filename}")
            self.log("="*60)
            
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
            print(f"✅ 状态更新完成")
            
            raise Exception(error_msg)
    
    def extract_video_title(self, youtube_url):
        """从YouTube URL提取视频标题"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(youtube_url, download=False)
                return info.get('title', '未知标题')
        except:
            return '未知标题'