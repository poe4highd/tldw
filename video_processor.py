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

class LanguageConfig:
    """语言配置和模型映射"""
    # 支持的语言列表
    SUPPORTED_LANGUAGES = {
        'zh': '中文',
        'en': 'English', 
        'ja': '日本語',
        'ko': '한국어',
        'es': 'Español',
        'fr': 'Français',
        'de': 'Deutsch',
        'it': 'Italiano',
        'pt': 'Português',
        'ru': 'Русский',
        'ar': 'العربية',
        'hi': 'हिन्दी'
    }
    
    # 语言对应的最佳Whisper模型
    LANGUAGE_MODEL_MAP = {
        'zh': 'medium',     # 中文用medium模型，平衡效果和速度
        'en': 'base',       # 英文用base模型，效果好且快
        'ja': 'small',      # 日文用small模型
        'ko': 'small',      # 韩文用small模型
        'es': 'base',       # 西班牙文用base模型
        'fr': 'base',       # 法文用base模型
        'de': 'base',       # 德文用base模型
        'default': 'small'  # 默认用small模型
    }
    
    # 语言检测置信度阈值
    LANGUAGE_DETECTION_THRESHOLD = 0.7
    
    @classmethod
    def get_optimal_model(cls, language):
        """根据语言获取最佳模型"""
        return cls.LANGUAGE_MODEL_MAP.get(language, cls.LANGUAGE_MODEL_MAP['default'])
    
    @classmethod 
    def get_language_name(cls, language_code):
        """获取语言的显示名称"""
        return cls.SUPPORTED_LANGUAGES.get(language_code, language_code)

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
    
    def detect_audio_language(self, audio_file, video_id=None):
        """检测音频文件的语言"""
        try:
            self.log("🔍 开始检测音频语言...")
            
            # 加载一个小模型用于语言检测
            detection_model = whisper.load_model("tiny")
            
            # 只加载前30秒用于语言检测
            import whisper
            audio = whisper.load_audio(audio_file)
            audio = whisper.pad_or_trim(audio)  # 取前30秒
            
            # 获取mel频谱
            mel = whisper.log_mel_spectrogram(audio).to(detection_model.device)
            
            # 检测语言
            _, probs = detection_model.detect_language(mel)
            detected_language = max(probs, key=probs.get)
            confidence = probs[detected_language]
            
            self.log(f"🔍 检测到语言: {LanguageConfig.get_language_name(detected_language)} ({detected_language})")
            self.log(f"📊 检测置信度: {confidence:.3f}")
            
            # 如果置信度足够高，保存检测结果
            if confidence >= LanguageConfig.LANGUAGE_DETECTION_THRESHOLD:
                if video_id:
                    self.db.update_language_info(video_id, detected_language=detected_language)
                self.log(f"✅ 语言检测成功: {LanguageConfig.get_language_name(detected_language)}")
                return detected_language, confidence
            else:
                self.log(f"⚠️ 语言检测置信度不足 ({confidence:.3f} < {LanguageConfig.LANGUAGE_DETECTION_THRESHOLD})，使用默认语言")
                return 'zh', confidence  # 默认中文
                
        except Exception as e:
            self.log(f"❌ 语言检测失败: {str(e)}")
            return 'zh', 0.0  # 默认中文
    
    def get_transcription_language(self, video_id):
        """获取转录使用的语言"""
        # 1. 优先使用用户强制指定的语言
        lang_info = self.db.get_language_info(video_id)
        if lang_info and lang_info.get('forced_language'):
            self.log(f"👤 使用用户指定语言: {LanguageConfig.get_language_name(lang_info['forced_language'])}")
            return lang_info['forced_language']
        
        # 2. 使用检测到的语言
        if lang_info and lang_info.get('detected_language'):
            self.log(f"🔍 使用检测到的语言: {LanguageConfig.get_language_name(lang_info['detected_language'])}")
            return lang_info['detected_language']
        
        # 3. 默认中文
        self.log("📝 使用默认语言: 中文")
        return 'zh'

    def load_whisper_model(self, language=None):
        """延迟加载Whisper模型 - 智能选择模型和设备"""
        # 根据语言确定最佳模型
        if language:
            optimal_model = LanguageConfig.get_optimal_model(language)
            self.log(f"🎯 根据语言 {LanguageConfig.get_language_name(language)} 选择模型: {optimal_model}")
        else:
            # 获取最优设备配置的默认模型
            device_info = self.get_optimal_device()
            optimal_model = device_info['optimal_model']
            
        if self.whisper_model is None or (language and optimal_model != getattr(self, 'current_model_name', None)):
            # 获取最优设备配置
            device_info = self.get_optimal_device()
            device = device_info['type']
            model_name = optimal_model
            
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
                self.current_model_name = model_name  # 记录当前模型名称
                self.log(f"✅ Whisper {model_name} 模型加载完成 (设备: {device})")
                
                # 显示模型信息
                model_params = sum(p.numel() for p in self.whisper_model.parameters()) / 1e6
                self.log(f"📊 模型参数量: {model_params:.1f}M")
                
            except Exception as e:
                # 如果首选模型加载失败，回退到最小模型
                self.log(f"⚠️ {model_name}模型加载失败，回退到tiny模型: {str(e)}")
                try:
                    self.whisper_model = whisper.load_model("tiny", device="cpu")
                    self.current_model_name = "tiny"  # 记录回退模型名称
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
    
    def transcribe_audio(self, audio_file, video_id=None, force_retranscribe=False):
        """使用Whisper转录音频 - 支持智能语言检测"""
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
            
            # 智能语言检测和模型选择
            if video_id:
                # 首先尝试检测语言(如果还没有检测过)
                lang_info = self.db.get_language_info(video_id)
                if not lang_info or not lang_info.get('detected_language'):
                    detected_lang, confidence = self.detect_audio_language(audio_file, video_id)
                
                # 获取转录语言
                transcription_language = self.get_transcription_language(video_id)
            else:
                # 没有video_id时，直接检测语言
                transcription_language, _ = self.detect_audio_language(audio_file)
            
            # 根据语言加载最佳模型
            model = self.load_whisper_model(transcription_language)
            self.log(f"🎙️ 开始转录音频文件: {audio_file}")
            self.log(f"🌐 使用语言: {LanguageConfig.get_language_name(transcription_language)} ({transcription_language})")
            
            # 优化的转录参数 - 使用检测到的语言
            transcribe_options = {
                'language': transcription_language,  # 使用检测到的语言
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
            corrected_text = self.correct_transcript_with_gpt(result['text'], transcription_language)
            
            # 保存校正后的纯文本转录
            with open(transcript_file, 'w', encoding='utf-8') as f:
                f.write(corrected_text)
            
            # 计算并保存字幕质量评分
            if video_id:
                quality_score = self._calculate_text_quality_score(corrected_text)
                self.db.update_subtitle_quality(video_id, quality_score)
            
            print(f"✅ 转录完成，保存到: {srt_file}")
            
            return corrected_text, srt_file, merged_segments
            
        except Exception as e:
            raise Exception(f"语音转录失败: {str(e)}")
    
    def is_sentence_end(self, text):
        """判断文本是否为句子结尾"""
        # 中文句子结尾标点
        chinese_endings = ['。', '！', '？', '；']
        # 英文句子结尾标点  
        english_endings = ['.', '!', '?', ';']
        
        text = text.strip()
        if not text:
            return False
            
        last_char = text[-1]
        return last_char in chinese_endings or last_char in english_endings
    
    def is_natural_pause(self, text):
        """判断是否为自然停顿点（逗号、冒号等）"""
        pause_marks = ['，', '、', '：', '；', ',', ':', ';', '--', '——']
        text = text.strip()
        if not text:
            return False
        return text[-1] in pause_marks
    
    def calculate_sentence_score(self, text):
        """计算文本的句子完整性评分"""
        score = 0
        text = text.strip()
        
        # 句子结尾标点加分
        if self.is_sentence_end(text):
            score += 10
        
        # 自然停顿点加分
        elif self.is_natural_pause(text):
            score += 5
        
        # 长度评分（20-80字符较理想）
        length = len(text)
        if 20 <= length <= 80:
            score += 8
        elif 10 <= length <= 120:
            score += 5
        elif length < 10:
            score -= 3
        
        # 完整词汇结尾加分
        if text and text[-1].isalnum():
            score += 2
        
        return score

    def merge_short_segments(self, segments, target_duration=25.0, max_duration=45.0):
        """
        智能合并短片段，优化句子完整性和自然度
        
        Args:
            segments: 原始片段列表
            target_duration: 目标片段时长（秒）
            max_duration: 最大片段时长（秒）
        """
        if not segments:
            return segments
        
        self.log("📝 开始智能字幕合并...")
        
        merged_segments = []
        current_segment = None
        
        for i, segment in enumerate(segments):
            if not isinstance(segment, dict):
                continue
                
            start = segment.get('start', 0)
            end = segment.get('end', 0)
            text = segment.get('text', '').strip()
            
            if not text:
                continue
            
            if current_segment is None:
                # 开始新片段
                current_segment = {
                    'start': start,
                    'end': end,
                    'text': text,
                    'original_segments': [segment]
                }
                continue
            
            # 计算当前片段信息
            current_duration = current_segment['end'] - current_segment['start']
            gap = start - current_segment['end']
            new_duration = end - current_segment['start']
            
            # 句子完整性评分
            current_score = self.calculate_sentence_score(current_segment['text'])
            combined_score = self.calculate_sentence_score(current_segment['text'] + ' ' + text)
            
            # 合并判断逻辑
            should_merge = False
            
            # 1. 基础条件：时间间隔和最大长度限制
            if gap <= 2.0 and new_duration <= max_duration:
                
                # 2. 如果当前片段未完成句子，倾向于合并
                if current_score < 8:
                    should_merge = True
                
                # 3. 如果合并后句子更完整
                elif combined_score > current_score + 3:
                    should_merge = True
                
                # 4. 当前片段太短，需要合并
                elif current_duration < 8.0:
                    should_merge = True
                
                # 5. 目标时长内且句子不完整
                elif current_duration < target_duration and not self.is_sentence_end(current_segment['text']):
                    should_merge = True
            
            # 执行合并或分割
            if should_merge:
                # 合并片段
                current_segment['end'] = end
                current_segment['text'] += ' ' + text
                current_segment['original_segments'].append(segment)
            else:
                # 分割：保存当前片段，开始新片段
                merged_segments.append(current_segment)
                current_segment = {
                    'start': start,
                    'end': end,
                    'text': text,
                    'original_segments': [segment]
                }
        
        # 保存最后一个片段
        if current_segment is not None:
            merged_segments.append(current_segment)
        
        # 统计信息
        avg_duration = sum(seg['end'] - seg['start'] for seg in merged_segments) / len(merged_segments) if merged_segments else 0
        complete_sentences = sum(1 for seg in merged_segments if self.is_sentence_end(seg['text']))
        
        self.log(f"📊 字幕合并完成:")
        self.log(f"   原始片段: {len(segments)} → 合并后: {len(merged_segments)}")
        self.log(f"   平均时长: {avg_duration:.1f}秒")
        self.log(f"   完整句子: {complete_sentences}/{len(merged_segments)} ({complete_sentences/len(merged_segments)*100:.1f}%)")
        
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
            self.log("🤖 发送GPT请求...")
            response = self.openai_client.chat.completions.create(
                model="gpt-4",  # 确保使用正确的模型名称
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1500  # 限制输出token数量
            )
            self.log("✅ GPT请求成功")
        except Exception as e:
            self.log(f"❌ GPT请求失败: {str(e)}")
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
                    self.log("✅ gpt-4-turbo请求成功")
                except Exception as e2:
                    # 如果还是失败，尝试缩短文本
                    self.log(f"⚠️ gpt-4-turbo也失败，缩短文本重试...")
                    try:
                        # 缩短内容重试
                        shortened_content = timestamped_content[:3000]  # 缩短时间戳内容
                        shortened_prompt = prompt.replace(timestamped_content, shortened_content)
                        response = self.openai_client.chat.completions.create(
                            model="gpt-4",
                            messages=[{"role": "user", "content": shortened_prompt}],
                            temperature=0.3,
                            max_tokens=1500
                        )
                        self.log("✅ 缩短内容后请求成功")
                    except Exception as e3:
                        self.log(f"❌ 所有GPT重试都失败: {str(e3)}")
                        return self._generate_fallback_analysis(transcript, segments)
            elif "rate" in str(e).lower() or "quota" in str(e).lower():
                self.log(f"⚠️ API配额或速率限制，生成备用简报")
                return self._generate_fallback_analysis(transcript, segments)
            elif "api" in str(e).lower() or "network" in str(e).lower() or "connection" in str(e).lower():
                self.log(f"⚠️ 网络或API连接问题，生成备用简报")
                return self._generate_fallback_analysis(transcript, segments)
            else:
                self.log(f"⚠️ 未知GPT错误，生成备用简报")
                return self._generate_fallback_analysis(transcript, segments)
        
        # 添加GPT响应调试信息
        gpt_response = response.choices[0].message.content
        self.log(f"🤖 GPT响应内容长度: {len(gpt_response) if gpt_response else 0}")
        
        if not gpt_response or gpt_response.strip() == "":
            self.log("❌ GPT返回空响应，生成默认简报")
            # 生成基础简报作为fallback
            return self._generate_fallback_analysis(transcript, segments)
        
        # 打印前200个字符用于调试
        self.log(f"🔍 GPT响应前200字符: {gpt_response[:200]}")
        
        try:
            analysis_result = json.loads(gpt_response)
        except json.JSONDecodeError as e:
            self.log(f"❌ JSON解析失败: {str(e)}")
            self.log(f"🔍 GPT完整响应: {gpt_response}")
            
            # 尝试修复常见的JSON格式问题
            cleaned_response = gpt_response.strip()
            
            # 移除可能的代码块标记
            if cleaned_response.startswith("```json"):
                cleaned_response = cleaned_response.replace("```json", "").replace("```", "").strip()
                self.log(f"🔧 尝试移除代码块标记")
            elif cleaned_response.startswith("```"):
                cleaned_response = cleaned_response.replace("```", "").strip()
                self.log(f"🔧 尝试移除通用代码块标记")
            
            # 移除可能的前缀文本
            if "{" in cleaned_response:
                json_start = cleaned_response.find("{")
                cleaned_response = cleaned_response[json_start:]
                self.log(f"🔧 尝试移除JSON前的文本")
            
            # 移除可能的后缀文本
            if "}" in cleaned_response:
                json_end = cleaned_response.rfind("}") + 1
                cleaned_response = cleaned_response[:json_end]
                self.log(f"🔧 尝试移除JSON后的文本")
            
            try:
                analysis_result = json.loads(cleaned_response)
                self.log(f"✅ JSON修复成功")
            except json.JSONDecodeError as e2:
                self.log(f"❌ JSON修复失败: {str(e2)}")
                self.log(f"🔧 生成备用简报")
                # 如果JSON完全无法解析，生成fallback
                return self._generate_fallback_analysis(transcript, segments)
        
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

    def _generate_fallback_analysis(self, transcript, segments):
        """当GPT失败时生成基础简报作为fallback"""
        self.log("🔧 生成备用分析简报...")
        
        # 简单的文本统计分析
        total_duration = segments[-1].get('end', 0) if segments else 0
        total_segments = len(segments)
        
        # 基础摘要
        summary = f"该视频时长约{int(total_duration//60)}分{int(total_duration%60)}秒，共包含{total_segments}段字幕内容。"
        
        # 生成基础要点（基于时间分段）
        key_points = []
        if segments:
            # 将视频分成3-5个时间段
            num_points = min(5, max(3, total_segments // 10))
            segment_size = len(segments) // num_points
            
            for i in range(num_points):
                start_idx = i * segment_size
                end_idx = min((i + 1) * segment_size, len(segments))
                
                if start_idx < len(segments):
                    segment_text = ' '.join([seg.get('text', '') for seg in segments[start_idx:end_idx]])
                    segment_start = segments[start_idx].get('start', 0)
                    
                    # 截取前100字符作为要点
                    point_text = segment_text[:100] + ("..." if len(segment_text) > 100 else "")
                    
                    key_points.append({
                        "point": f"第{i+1}段内容要点",
                        "explanation": point_text,
                        "timestamp": int(segment_start),
                        "quote": segment_text[:200] + ("..." if len(segment_text) > 200 else "")
                    })
        
        if not key_points:
            # 如果没有segments，生成一个默认要点
            key_points.append({
                "point": "视频内容",
                "explanation": "视频包含语音内容，但自动分析失败。",
                "timestamp": 0,
                "quote": transcript[:200] + ("..." if len(transcript) > 200 else "")
            })
        
        return {
            "summary": summary,
            "key_points": key_points
        }

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
            self.log(f"❌ GPT分块请求失败: {str(e)}")
            if "token" in str(e).lower() or "context" in str(e).lower():
                # 如果chunk仍然太大，进一步缩短
                self.log("⚠️ 进一步缩短文本重试...")
                shortened_chunk = chunk_text[:2000]
                shortened_prompt = prompt.replace(chunk_text, shortened_chunk)
                try:
                    response = self.openai_client.chat.completions.create(
                        model="gpt-4",
                        messages=[{"role": "user", "content": shortened_prompt}],
                        temperature=0.3,
                        max_tokens=1200
                    )
                except Exception as e2:
                    self.log(f"❌ 缩短文本后仍失败: {str(e2)}")
                    # 返回空结果
                    return {"summary": "分块分析失败", "key_points": []}
            else:
                self.log(f"❌ 其他GPT错误: {str(e)}")
                return {"summary": "分块分析失败", "key_points": []}
        
        # 安全的JSON解析
        try:
            gpt_response = response.choices[0].message.content
            if not gpt_response or gpt_response.strip() == "":
                self.log("❌ GPT分块返回空响应")
                return {"summary": "分块分析返回空响应", "key_points": []}
            
            return json.loads(gpt_response)
        except json.JSONDecodeError as e:
            self.log(f"❌ GPT分块JSON解析失败: {str(e)}")
            # 返回基础结果
            return {
                "summary": f"此部分包含{len(chunk_text)}字符的内容",
                "key_points": [{
                    "point": "内容片段",
                    "explanation": chunk_text[:100] + "...",
                    "quote": chunk_text[:200] + "..."
                }]
            }

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
    
    def correct_transcript_with_gpt(self, transcript_text, language='zh'):
        """使用GPT进行智能字幕校正和断句优化"""
        try:
            self.log("🔍 开始GPT智能字幕校正...")
            
            # 分段处理，避免token限制
            max_chars_per_chunk = 1800
            chunks = self._split_text_for_correction(transcript_text, max_chars_per_chunk)
            
            corrected_chunks = []
            total_corrections = 0
            
            for i, chunk in enumerate(chunks):
                self.log(f"📝 校正第 {i+1}/{len(chunks)} 段文本...")
                
                corrected_chunk, corrections = self._correct_text_chunk(chunk, language)
                corrected_chunks.append(corrected_chunk)
                total_corrections += corrections
            
            # 合并校正后的文本
            corrected_transcript = ' '.join(corrected_chunks)
            
            # 计算改进评分
            quality_score = self._calculate_text_quality_score(corrected_transcript)
            
            self.log(f"✅ GPT字幕校正完成:")
            self.log(f"   总计修正: {total_corrections} 处")
            self.log(f"   质量评分: {quality_score:.1f}/10")
            
            return corrected_transcript
            
        except Exception as e:
            self.log(f"❌ GPT字幕校正失败: {str(e)}，使用原始转录")
            return transcript_text
    
    def _split_text_for_correction(self, text, max_chars):
        """智能分割文本用于校正"""
        chunks = []
        
        # 优先按句子分割
        sentences = []
        for delimiter in ['。', '！', '？', '.', '!', '?']:
            if delimiter in text:
                sentences = text.split(delimiter)
                # 重新加上分隔符
                sentences = [s + delimiter for s in sentences[:-1]] + [sentences[-1]] if sentences else []
                break
        
        if not sentences:
            # 如果没有句子分隔符，按逗号分割
            sentences = [s + '，' for s in text.split('，')[:-1]] + [text.split('，')[-1]] if '，' in text else [text]
        
        current_chunk = ""
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
                
            if len(current_chunk + sentence) <= max_chars:
                current_chunk += sentence
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = sentence
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        return chunks
    
    def _correct_text_chunk(self, chunk, language):
        """校正单个文本块"""
        if language == 'zh':
            return self._correct_chinese_chunk(chunk)
        elif language == 'en':
            return self._correct_english_chunk(chunk)
        else:
            return self._correct_multilingual_chunk(chunk, language)
    
    def _correct_chinese_chunk(self, chunk):
        """校正中文文本块"""
        prompt = f"""
请对以下中文转录文本进行智能校正和优化：

原文：
{chunk}

任务：
1. 同音字纠错：纠正明显的同音字错误（如：在→再，的→得，和→合等）
2. 标点符号优化：添加适当的逗号、句号，改善句子流畅度
3. 断句优化：将过长句子合理分割，将过短片段合并
4. 语法完善：修正明显的语法错误，保持自然表达

要求：
- 保持原意和语言风格不变
- 优先修正明显错误，避免过度修改
- 确保每个句子完整且意思清晰
- 适当添加标点符号提高可读性
- 直接返回校正后的文本，无需解释

校正后的文本：
"""
        
        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,  # 稍高温度允许创造性校正
                max_tokens=1000
            )
            
            corrected_text = response.choices[0].message.content.strip()
            
            # 计算修正数量
            corrections = self._count_corrections(chunk, corrected_text)
            
            return corrected_text, corrections
            
        except Exception as e:
            self.log(f"⚠️ 文本块校正失败: {str(e)}")
            return chunk, 0
    
    def _correct_english_chunk(self, chunk):
        """校正英文文本块"""
        prompt = f"""
Please correct and optimize the following English transcript:

Original:
{chunk}

Tasks:
1. Fix obvious transcription errors and typos
2. Add appropriate punctuation (commas, periods) for readability
3. Break long sentences and merge short fragments appropriately
4. Correct grammar while maintaining natural speech patterns

Requirements:
- Preserve original meaning and speaking style
- Focus on clear errors, avoid over-editing
- Ensure each sentence is complete and clear
- Add punctuation to improve readability
- Return only the corrected text without explanations

Corrected text:
"""
        
        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1000
            )
            
            corrected_text = response.choices[0].message.content.strip()
            corrections = self._count_corrections(chunk, corrected_text)
            
            return corrected_text, corrections
            
        except Exception as e:
            self.log(f"⚠️ English chunk correction failed: {str(e)}")
            return chunk, 0
    
    def _correct_multilingual_chunk(self, chunk, language):
        """校正多语言文本块"""
        lang_name = LanguageConfig.get_language_name(language)
        
        prompt = f"""
Please correct and optimize the following {lang_name} transcript:

Original:
{chunk}

Tasks:
1. Fix transcription errors and improve accuracy
2. Add appropriate punctuation for better readability
3. Optimize sentence structure and flow
4. Maintain natural speaking style

Requirements:
- Preserve original meaning and tone
- Focus on clear improvements
- Ensure sentences are complete and clear
- Return only the corrected text

Corrected text:
"""
        
        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1000
            )
            
            corrected_text = response.choices[0].message.content.strip()
            corrections = self._count_corrections(chunk, corrected_text)
            
            return corrected_text, corrections
            
        except Exception as e:
            self.log(f"⚠️ {lang_name} chunk correction failed: {str(e)}")
            return chunk, 0
    
    def _count_corrections(self, original, corrected):
        """估算校正数量"""
        if original == corrected:
            return 0
        
        # 简单估算：基于字符差异和标点变化
        char_diff = abs(len(corrected) - len(original))
        punct_orig = sum(1 for c in original if c in '，。！？、；：')
        punct_corr = sum(1 for c in corrected if c in '，。！？、；：')
        punct_diff = abs(punct_corr - punct_orig)
        
        return max(1, char_diff // 5 + punct_diff)
    
    def _calculate_text_quality_score(self, text):
        """计算文本质量评分"""
        score = 5.0  # 基础分
        
        # 句子完整性（标点符号）
        sentences = len([c for c in text if c in '。！？.!?'])
        total_chars = len(text)
        if total_chars > 0:
            sentence_density = sentences / (total_chars / 100)  # 每100字符的句子数
            if 0.5 <= sentence_density <= 2.0:  # 理想范围
                score += 2.0
            elif 0.2 <= sentence_density <= 3.0:
                score += 1.0
        
        # 标点符号丰富度
        punct_variety = len(set(text) & set('，。！？、；：,.!?;:'))
        score += min(2.0, punct_variety * 0.3)
        
        # 文本流畅度（连续标点或重复字符扣分）
        if '，，' in text or '。。' in text or '  ' in text:
            score -= 0.5
        
        return min(10.0, score)
    
    def translate_transcript(self, video_id, target_language='en', source_language=None):
        """翻译字幕到目标语言"""
        try:
            self.log(f"🌐 开始翻译字幕到 {LanguageConfig.get_language_name(target_language)}...")
            
            # 获取语言信息
            lang_info = self.db.get_language_info(video_id)
            if not source_language:
                source_language = lang_info.get('detected_language', 'zh') if lang_info else 'zh'
            
            # 读取原始转录文本
            video_info = self.db.get_video_info(video_id)
            if not video_info:
                raise Exception("视频信息不存在")
            
            # 查找转录文件
            youtube_url = video_info['youtube_url']
            yt_video_id = self.extract_video_id(youtube_url)
            transcript_file = f"transcripts/{yt_video_id}.txt"
            
            if not os.path.exists(transcript_file):
                raise Exception("转录文件不存在，请先进行转录")
            
            # 读取转录内容
            with open(transcript_file, 'r', encoding='utf-8') as f:
                source_text = f.read()
            
            # 执行翻译
            translated_text = self._translate_text_with_gpt(source_text, source_language, target_language)
            
            # 保存翻译结果
            self._save_translation_files(yt_video_id, translated_text, source_text, target_language, source_language)
            
            # 更新数据库
            self.db.update_language_info(video_id, target_language=target_language)
            self.db.update_translation_status(video_id, True)
            
            # 更新可用语言列表
            available_languages = lang_info.get('available_languages', []) if lang_info else []
            if source_language not in available_languages:
                available_languages.append(source_language)
            if target_language not in available_languages:
                available_languages.append(target_language)
            self.db.update_available_languages(video_id, available_languages)
            
            self.log(f"✅ 翻译完成: {LanguageConfig.get_language_name(source_language)} → {LanguageConfig.get_language_name(target_language)}")
            
            return translated_text
            
        except Exception as e:
            self.log(f"❌ 翻译失败: {str(e)}")
            raise Exception(f"翻译失败: {str(e)}")
    
    def _translate_text_with_gpt(self, text, source_lang, target_lang):
        """使用GPT翻译文本"""
        source_lang_name = LanguageConfig.get_language_name(source_lang)
        target_lang_name = LanguageConfig.get_language_name(target_lang)
        
        # 分段翻译，避免token限制
        max_chars_per_chunk = 2000
        chunks = self._split_text_for_correction(text, max_chars_per_chunk)
        
        translated_chunks = []
        
        for i, chunk in enumerate(chunks):
            self.log(f"📝 翻译第 {i+1}/{len(chunks)} 段文本...")
            
            translated_chunk = self._translate_chunk(chunk, source_lang_name, target_lang_name, source_lang, target_lang)
            translated_chunks.append(translated_chunk)
        
        return ' '.join(translated_chunks)
    
    def _translate_chunk(self, chunk, source_lang_name, target_lang_name, source_lang, target_lang):
        """翻译单个文本块"""
        if source_lang == target_lang:
            return chunk
        
        # 构建翻译提示
        prompt = self._build_translation_prompt(chunk, source_lang_name, target_lang_name, source_lang, target_lang)
        
        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,  # 稍高温度确保流畅翻译
                max_tokens=1200
            )
            
            translated_text = response.choices[0].message.content.strip()
            return translated_text
            
        except Exception as e:
            self.log(f"⚠️ 翻译块失败: {str(e)}")
            return chunk  # 返回原文
    
    def _build_translation_prompt(self, text, source_lang_name, target_lang_name, source_lang, target_lang):
        """构建翻译提示"""
        
        if target_lang == 'zh':
            return f"""
请将以下{source_lang_name}文本翻译成中文：

原文：
{text}

翻译要求：
1. 保持原文的意思和语调
2. 使用自然流畅的中文表达
3. 对于专业术语，提供准确的中文对应
4. 保持句子结构的逻辑性
5. 如果是口语化内容，翻译也要保持口语化风格
6. 直接返回翻译结果，不要添加解释

中文翻译：
"""
        elif target_lang == 'en':
            return f"""
Please translate the following {source_lang_name} text into English:

Original:
{text}

Translation requirements:
1. Preserve the original meaning and tone
2. Use natural and fluent English expressions
3. Provide accurate English equivalents for technical terms
4. Maintain logical sentence structure
5. If it's conversational content, keep the conversational style
6. Return only the translation without explanations

English translation:
"""
        else:
            return f"""
Please translate the following {source_lang_name} text into {target_lang_name}:

Original:
{text}

Translation requirements:
1. Preserve the original meaning and tone
2. Use natural and fluent {target_lang_name} expressions
3. Maintain the logical flow of ideas
4. Keep the original style (formal/informal)
5. Return only the translation without explanations

{target_lang_name} translation:
"""
    
    def _save_translation_files(self, video_id, translated_text, original_text, target_lang, source_lang):
        """保存翻译文件"""
        # 确保translations目录存在
        os.makedirs('transcripts/translations', exist_ok=True)
        
        # 保存翻译后的文本文件
        target_txt_file = f"transcripts/translations/{video_id}_{target_lang}.txt"
        with open(target_txt_file, 'w', encoding='utf-8') as f:
            f.write(translated_text)
        
        # 保存原文（如果还没有保存过）
        source_txt_file = f"transcripts/translations/{video_id}_{source_lang}.txt"
        if not os.path.exists(source_txt_file):
            with open(source_txt_file, 'w', encoding='utf-8') as f:
                f.write(original_text)
        
        self.log(f"💾 翻译文件已保存: {target_txt_file}")
        
        return target_txt_file
    
    def get_available_translations(self, video_id):
        """获取视频的可用翻译"""
        try:
            youtube_url = self.db.get_video_info(video_id)['youtube_url']
            yt_video_id = self.extract_video_id(youtube_url)
            
            translations = {}
            
            # 检查translations目录
            translations_dir = 'transcripts/translations'
            if os.path.exists(translations_dir):
                import glob
                pattern = f"{translations_dir}/{yt_video_id}_*.txt"
                files = glob.glob(pattern)
                
                for file in files:
                    filename = os.path.basename(file)
                    # 提取语言代码: {video_id}_{lang}.txt
                    lang_code = filename.split('_')[-1].replace('.txt', '')
                    if lang_code in LanguageConfig.SUPPORTED_LANGUAGES:
                        translations[lang_code] = {
                            'language': LanguageConfig.get_language_name(lang_code),
                            'file_path': file,
                            'exists': True
                        }
            
            return translations
            
        except Exception as e:
            self.log(f"❌ 获取翻译列表失败: {str(e)}")
            return {}

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
            max-width: 1600px;
            margin: 0 auto;
            padding: 20px;
        }}

        /* 顶部区域：视频 + 摘要 */
        .top-section {{
            background: #fff;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}

        .header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 15px;
            flex-wrap: wrap;
            gap: 10px;
        }}

        .header h1 {{
            margin: 0;
            flex: 1;
            min-width: 200px;
        }}

        .header-actions {{
            display: flex;
            gap: 10px;
            align-items: center;
        }}

        .source-btn {{
            background: linear-gradient(135deg, #ff6b6b, #ee5a24);
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 25px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            transition: all 0.3s ease;
            box-shadow: 0 2px 8px rgba(238, 90, 36, 0.3);
        }}

        .source-btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(238, 90, 36, 0.4);
        }}

        .gen-time {{
            color: #666;
            font-size: 0.85em;
        }}

        .video-container {{
            background: #000;
            border-radius: 8px;
            overflow: hidden;
            margin-bottom: 15px;
        }}

        .video-wrapper {{
            position: relative;
            padding-bottom: 56.25%;
            height: 0;
            overflow: hidden;
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
            padding: 15px 20px;
            border-radius: 8px;
            border-left: 4px solid #2196f3;
        }}

        .summary h2 {{
            margin: 0 0 10px 0;
            font-size: 1.1em;
            color: #1565c0;
        }}

        .summary p {{
            margin: 0;
            color: #333;
        }}

        /* 下方分屏区域 */
        .main-content {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            min-height: 60vh;
        }}

        /* 左侧：关键要点 */
        .key-points {{
            background: #fff;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            max-height: calc(100vh - 400px);
            overflow-y: auto;
        }}

        .key-points h2 {{
            margin: 0 0 15px 0;
            position: sticky;
            top: 0;
            background: #fff;
            padding: 5px 0 10px 0;
            border-bottom: 2px solid #f0f0f0;
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

        .key-point h3 {{
            margin: 0 0 8px 0;
            font-size: 1em;
            color: #333;
        }}

        .key-point > p {{
            margin: 0 0 10px 0;
            color: #555;
            font-size: 0.95em;
        }}

        .timestamp {{
            background: #007bff;
            color: white;
            padding: 6px 12px;
            border-radius: 20px;
            text-decoration: none;
            cursor: pointer;
            font-size: 0.85em;
            font-weight: 500;
            transition: all 0.2s ease;
            display: inline-block;
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
            font-size: 0.9em;
        }}

        /* 右侧：完整字幕 */
        .subtitles-section {{
            background: #fff;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            display: flex;
            flex-direction: column;
            max-height: calc(100vh - 400px);
        }}

        .subtitles-header {{
            padding: 15px 20px;
            background: #28a745;
            color: white;
            border-radius: 8px 8px 0 0;
            font-weight: 600;
            font-size: 1.1em;
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .subtitles-container {{
            flex: 1;
            overflow-y: auto;
            padding: 0;
        }}

        .subtitle-line {{
            padding: 10px 20px;
            border-bottom: 1px solid #f0f0f0;
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            align-items: flex-start;
            gap: 12px;
        }}

        .subtitle-line:hover {{
            background: #e3f2fd;
        }}

        /* 同时间戳分组高亮 */
        .subtitle-line.group-hover {{
            background: #fff3e0;
        }}

        .subtitle-line.active {{
            background: #fff3cd;
            border-left: 4px solid #ffc107;
            font-weight: 500;
        }}

        .subtitle-line.clicked {{
            background: #d1ecf1;
            border-left: 4px solid #17a2b8;
        }}

        @keyframes highlight {{
            0% {{ background: #ffecb3; }}
            100% {{ background: #fff3cd; }}
        }}

        .subtitle-time {{
            color: #007bff;
            font-weight: bold;
            font-size: 0.85em;
            min-width: 50px;
            flex-shrink: 0;
        }}

        .subtitle-text {{
            color: #333;
            flex: 1;
        }}

        /* 响应式设计 */
        @media (max-width: 1024px) {{
            .main-content {{
                grid-template-columns: 1fr;
            }}

            .key-points,
            .subtitles-section {{
                max-height: 400px;
            }}
        }}

        @media (max-width: 768px) {{
            .container {{
                padding: 10px;
            }}

            .header {{
                flex-direction: column;
            }}

            .header-actions {{
                width: 100%;
                justify-content: space-between;
            }}

            .main-content {{
                gap: 15px;
            }}

            .key-point, .summary {{
                padding: 12px;
            }}
        }}

        /* 滚动条美化 */
        .key-points::-webkit-scrollbar,
        .subtitles-container::-webkit-scrollbar {{
            width: 8px;
        }}

        .key-points::-webkit-scrollbar-track,
        .subtitles-container::-webkit-scrollbar-track {{
            background: #f1f1f1;
            border-radius: 4px;
        }}

        .key-points::-webkit-scrollbar-thumb,
        .subtitles-container::-webkit-scrollbar-thumb {{
            background: #c1c1c1;
            border-radius: 4px;
        }}

        .key-points::-webkit-scrollbar-thumb:hover,
        .subtitles-container::-webkit-scrollbar-thumb:hover {{
            background: #a1a1a1;
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- 顶部区域：标题 + 视频 + 摘要 -->
        <div class="top-section">
            <div class="header">
                <h1>{video_title}</h1>
                <div class="header-actions">
                    <a href="{youtube_url}" target="_blank" class="source-btn">
                        ▶️ 原视频
                    </a>
                    <span class="gen-time">生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}</span>
                </div>
            </div>

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

        <!-- 下方分屏区域 -->
        <div class="main-content">
            <!-- 左侧：关键要点 -->
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

            <!-- 右侧：完整字幕 -->
            <div class="subtitles-section">
                <div class="subtitles-header">
                    📝 完整字幕
                </div>
                <div class="subtitles-container" id="subtitles-container">
                    <div id="subtitles-list">
                        <!-- 字幕内容将由JavaScript动态生成 -->
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
        let currentHighlightedIds = [];  // 支持多个同时高亮
        let progressUpdateTimer = null;
        let timestampGroups = {{}};  // 按时间戳分组的字幕

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
            buildTimestampGroups();
            generateSubtitlesList();
        }}

        // 构建时间戳分组（按秒分组）
        function buildTimestampGroups() {{
            subtitlesData.forEach(subtitle => {{
                const timeKey = Math.floor(subtitle.start);
                if (!timestampGroups[timeKey]) {{
                    timestampGroups[timeKey] = [];
                }}
                timestampGroups[timeKey].push(subtitle.id);
            }});
        }}

        // 获取同一时间戳的所有字幕ID
        function getSameTimestampIds(subtitleId) {{
            const subtitle = subtitlesData.find(s => s.id === subtitleId);
            if (!subtitle) return [subtitleId];
            const timeKey = Math.floor(subtitle.start);
            return timestampGroups[timeKey] || [subtitleId];
        }}

        function onPlayerStateChange(event) {{
            if (event.data === YT.PlayerState.PLAYING) {{
                startProgressMonitoring();
            }} else {{
                stopProgressMonitoring();
            }}
        }}

        function startProgressMonitoring() {{
            if (progressUpdateTimer) {{
                clearInterval(progressUpdateTimer);
            }}

            progressUpdateTimer = setInterval(() => {{
                if (player && player.getCurrentTime) {{
                    const currentTime = player.getCurrentTime();
                    updateSubtitleHighlight(currentTime);
                }}
            }}, 250);  // 更快的更新频率
        }}

        function stopProgressMonitoring() {{
            if (progressUpdateTimer) {{
                clearInterval(progressUpdateTimer);
                progressUpdateTimer = null;
            }}
        }}

        // 更新字幕高亮 - 支持同时间戳多字幕高亮
        function updateSubtitleHighlight(currentTime) {{
            const currentSubtitles = findCurrentSubtitles(currentTime);
            const newIds = currentSubtitles.map(s => s.id);

            // 检查是否需要更新
            if (JSON.stringify(newIds) === JSON.stringify(currentHighlightedIds)) {{
                return;
            }}

            // 移除旧高亮
            currentHighlightedIds.forEach(id => {{
                const el = document.querySelector(`[data-subtitle-id="${{id}}"]`);
                if (el) el.classList.remove('active');
            }});

            // 添加新高亮
            newIds.forEach(id => {{
                const el = document.querySelector(`[data-subtitle-id="${{id}}"]`);
                if (el) {{
                    el.classList.add('active');
                }}
            }});

            // 自动滚动到第一个高亮字幕
            if (newIds.length > 0 && newIds[0] !== currentHighlightedIds[0]) {{
                const firstEl = document.querySelector(`[data-subtitle-id="${{newIds[0]}}"]`);
                if (firstEl && !firstEl.isScrolling) {{
                    firstEl.isScrolling = true;
                    firstEl.scrollIntoView({{
                        behavior: 'smooth',
                        block: 'center'
                    }});
                    setTimeout(() => {{
                        firstEl.isScrolling = false;
                    }}, 1000);
                }}
            }}

            currentHighlightedIds = newIds;
        }}

        // 查找当前时间点的所有字幕
        function findCurrentSubtitles(currentTime) {{
            return subtitlesData.filter(s =>
                currentTime >= s.start && currentTime <= s.end
            );
        }}

        // 跳转到指定时间 - 保持播放/暂停状态
        function seekToTime(seconds, clickedElement = null) {{
            if (player && player.seekTo) {{
                // 记录当前播放状态
                const wasPlaying = player.getPlayerState && player.getPlayerState() === YT.PlayerState.PLAYING;

                player.seekTo(seconds, true);

                // 根据之前的状态决定是否播放
                if (wasPlaying) {{
                    player.playVideo();
                }}
                // 如果之前是暂停的，就保持暂停（不调用playVideo）

                // 添加点击反馈效果
                if (clickedElement) {{
                    document.querySelectorAll('.subtitle-line.clicked').forEach(el => {{
                        el.classList.remove('clicked');
                    }});
                    clickedElement.classList.add('clicked');
                    setTimeout(() => {{
                        clickedElement.classList.remove('clicked');
                    }}, 500);
                }}
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

                // 点击跳转
                subtitleDiv.onclick = (event) => {{
                    event.preventDefault();
                    seekToTime(subtitle.start, subtitleDiv);
                }};

                // hover时高亮同时间戳的所有字幕
                subtitleDiv.onmouseenter = () => {{
                    const sameIds = getSameTimestampIds(subtitle.id);
                    sameIds.forEach(id => {{
                        const el = document.querySelector(`[data-subtitle-id="${{id}}"]`);
                        if (el) el.classList.add('group-hover');
                    }});
                }};

                subtitleDiv.onmouseleave = () => {{
                    const sameIds = getSameTimestampIds(subtitle.id);
                    sameIds.forEach(id => {{
                        const el = document.querySelector(`[data-subtitle-id="${{id}}"]`);
                        if (el) el.classList.remove('group-hover');
                    }});
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

        // 键盘快捷键支持
        document.addEventListener('keydown', (event) => {{
            if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA') {{
                return;
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

        // 页面卸载时清理定时器
        window.addEventListener('beforeunload', () => {{
            stopProgressMonitoring();
        }});

        // 页面可见性变化时的优化
        document.addEventListener('visibilitychange', () => {{
            if (document.hidden) {{
                if (progressUpdateTimer) {{
                    clearInterval(progressUpdateTimer);
                    progressUpdateTimer = setInterval(() => {{
                        if (player && player.getCurrentTime) {{
                            updateSubtitleHighlight(player.getCurrentTime());
                        }}
                    }}, 2000);
                }}
            }} else {{
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
                transcript, srt_file, segments = self.transcribe_audio(audio_file, video_id, force_retranscribe)
                self.log(f"✅ 语音转录完成，共{len(segments)}个片段")
                
                # 更新使用的模型记录和转录检查点
                # 获取实际使用的模型名称
                actual_model = getattr(self, 'current_model_name', current_model)
                self.db.update_whisper_model(video_id, actual_model)
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