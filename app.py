from flask import Flask, request, render_template, jsonify, send_from_directory
from flask_cors import CORS
import os
import sys
import sqlite3
import threading
import logging
from dotenv import load_dotenv
from database import Database
from video_processor import VideoProcessor

load_dotenv()

# 配置日志 - 只显示重要信息
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# 降低第三方库的日志级别，减少噪音
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('openai').setLevel(logging.WARNING)
logging.getLogger('werkzeug').setLevel(logging.WARNING)

def print_environment_info():
    """打印环境诊断信息"""
    import sys
    import yt_dlp
    
    print("="*80)
    print("🔧 FLASK应用环境诊断")
    print("="*80)
    print(f"🐍 Python版本: {sys.version}")
    print(f"📍 Python路径: {sys.executable}")
    print(f"📦 yt-dlp版本: {yt_dlp.version.__version__}")
    print(f"📦 期望版本: 2025.06.30 (最新)")
    print(f"📂 当前工作目录: {os.getcwd()}")
    
    # 检查GPU和PyTorch
    try:
        import torch
        print(f"🚀 PyTorch版本: {torch.__version__}")
        print(f"🖥️ CUDA可用: {'✅' if torch.cuda.is_available() else '❌'}")
        if torch.cuda.is_available():
            print(f"🎮 GPU设备数: {torch.cuda.device_count()}")
            print(f"🎯 GPU名称: {torch.cuda.get_device_name(0)}")
        else:
            print("💻 将使用CPU进行AI处理")
    except ImportError:
        print("❌ PyTorch未安装")
    
    # 检查关键文件
    key_files = ['downloads', 'transcripts', 'reports']
    for folder in key_files:
        exists = "✅" if os.path.exists(folder) else "❌"
        print(f"📁 {folder}/ 目录: {exists}")
    
    # 检查conda环境
    conda_env = os.environ.get('CONDA_DEFAULT_ENV', 'None')
    print(f"🐍 Conda环境: {conda_env}")
    
    print("="*80)

app = Flask(__name__)
app.logger.setLevel(logging.INFO)

# CORS 配置 - 允许 Vercel 域名访问
CORS(app,
     origins=[
         "https://*.vercel.app",          # Vercel 部署
         "http://localhost:3000",         # 本地前端开发
         "http://localhost:5001",         # 本地后端
     ],
     supports_credentials=True,
     methods=["GET", "POST", "DELETE", "OPTIONS"],
     allow_headers=["Content-Type", "Authorization"]
)

print("🔧 初始化数据库...")
db = Database()
print(f"✅ 数据库初始化完成: {type(db)}")

print("🤖 初始化视频处理器...")
processor = VideoProcessor(db)
print(f"✅ 视频处理器初始化完成: {type(processor)}")
print(f"   - processor.db: {type(processor.db)}")
print(f"   - processor.log_messages: {len(processor.log_messages)} 条日志")

# 启动时打印环境信息
print_environment_info()

def extract_video_id_from_url(url):
    """从YouTube URL中提取视频ID"""
    import re
    patterns = [
        r'(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'(?:embed/)([a-zA-Z0-9_-]{11})',
        r'(?:shorts/)([a-zA-Z0-9_-]{11})'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

@app.route('/')
def home():
    """用户主页 - 展示已处理视频"""
    # 获取已完成的视频（按发布日期排序）
    completed_videos = db.get_completed_videos(order_by='publish_date')

    # 转换为字典格式，便于模板使用
    videos = []
    for video in completed_videos:
        video_id = extract_video_id_from_url(video[7]) if video[7] else None
        videos.append({
            'id': video[0],
            'title': video[1],
            'report_filename': video[2],
            'publish_date': video[3],
            'channel_name': video[4],
            'duration': video[5],
            'created_at': video[6],
            'video_id': video_id
        })

    return render_template('index.html', videos=videos)

@app.route('/dev')
def dev():
    """开发页面 - 提交表单和处理记录"""
    videos = db.get_all_videos()
    return render_template('dev.html', videos=videos)

@app.route('/submit', methods=['POST'])
def submit_url():
    """提交YouTube链接"""
    app.logger.info("🔵 开始处理/submit请求")
    
    youtube_url = request.form.get('youtube_url')
    app.logger.info(f"📹 收到YouTube URL: {youtube_url}")
    
    if not youtube_url:
        app.logger.warning("❌ 未提供YouTube链接")
        return jsonify({'error': '请提供YouTube链接'}), 400
    
    # 验证YouTube URL格式
    try:
        test_video_id = processor.extract_video_id(youtube_url)
        app.logger.info(f"✅ URL验证通过，视频ID: {test_video_id}")
    except ValueError as e:
        app.logger.warning(f"❌ 无效的YouTube链接: {youtube_url}, 错误: {str(e)}")
        return jsonify({'error': f'无效的YouTube链接格式: {str(e)}'}), 400
    
    # 检查URL是否已存在
    app.logger.info("🔍 检查URL是否已存在...")
    existing_video = db.get_video_by_url(youtube_url)
    if existing_video:
        # 解包数据库记录 - 现在包含检查点字段
        video_id = existing_video[0]
        url = existing_video[1] 
        title = existing_video[2]
        report_filename = existing_video[3]
        status = existing_video[4]
        created_at = existing_video[5]
        completed_at = existing_video[6]
        error_message = existing_video[7]
        whisper_model = existing_video[8]
        # 新的检查点字段: [9]download_completed, [10]transcribe_completed, [11]report_completed, [12]audio_file_path, [13]transcript_file_path
        
        app.logger.info(f"⚠️ 视频已存在，ID: {video_id}, 状态: {status}")
        
        # 使用检查点验证系统检查是否完全完成
        if processor.is_fully_completed(video_id):
            app.logger.info("✅ 视频已完全处理完成（所有检查点通过），拒绝重复处理")
            return jsonify({'error': '该视频已经处理过了', 'video_id': video_id})
        
        # 如果有任何检查点未完成，允许从检查点恢复
        next_checkpoint = processor.get_next_checkpoint(video_id)
        if next_checkpoint:
            app.logger.info(f"🔄 视频有未完成的检查点，将从 {next_checkpoint} 开始恢复处理")
            video_id = existing_video[0]  # 使用现有的video_id
        else:
            app.logger.info("⚠️ 检查点状态异常，拒绝处理")
            return jsonify({'error': '视频状态异常，请检查文件完整性', 'video_id': video_id})
    else:
        # 插入数据库记录
        app.logger.info("💾 插入新的数据库记录...")
        video_id = db.insert_video(youtube_url)
        app.logger.info(f"✅ 数据库插入成功，video_id: {video_id}")
    
    try:
        # 临时修复：直接同步处理，不使用线程
        app.logger.info(f"🚀 开始调用processor.process_video({video_id}, {youtube_url})")
        try:
            app.logger.info("📱 processor对象状态检查...")
            app.logger.info(f"   - processor类型: {type(processor)}")
            app.logger.info(f"   - processor.db: {type(processor.db)}")
            
            app.logger.info("🎬 即将调用process_video方法...")
            processor.process_video(video_id, youtube_url)
            app.logger.info("✅ process_video调用完成")
            
            return jsonify({'success': True, 'video_id': video_id, 'message': '视频处理完成'})
        except Exception as process_error:
            app.logger.error(f"❌ process_video异常: {str(process_error)}")
            import traceback
            app.logger.error(f"详细错误堆栈:\n{traceback.format_exc()}")
            
            # 更新数据库状态为失败
            db.update_video_status(video_id, 'failed', str(process_error))
            return jsonify({'error': f'视频处理失败: {str(process_error)}'}), 500
    
    except Exception as e:
        app.logger.error(f"❌ 总体处理异常: {str(e)}")
        import traceback
        app.logger.error(f"详细错误堆栈:\n{traceback.format_exc()}")
        return jsonify({'error': f'处理失败: {str(e)}'}), 500

@app.route('/status/<int:video_id>')
def get_status(video_id):
    """获取处理状态"""
    with sqlite3.connect(db.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT status, error_message, video_title, youtube_url FROM videos WHERE id=?', (video_id,))
        result = cursor.fetchone()
        
        if result:
            status, error_message, video_title, youtube_url = result
            
            # 检查文件状态
            file_status = get_file_status(youtube_url, video_title)
            
            return jsonify({
                'status': status, 
                'error': error_message,
                'title': video_title or '获取标题中...',
                'file_status': file_status
            })
        else:
            return jsonify({'error': '视频不存在'}), 404

def get_file_status(youtube_url, video_title):
    """检查相关文件的存在状态"""
    try:
        from video_processor import VideoProcessor
        temp_processor = VideoProcessor(db)
        yt_video_id = temp_processor.extract_video_id(youtube_url)
        
        # 检查MP3文件
        mp3_file = f"downloads/{yt_video_id}.mp3"
        mp3_exists = os.path.exists(mp3_file)
        mp3_size = 0
        if mp3_exists:
            mp3_size = os.path.getsize(mp3_file) / (1024 * 1024)  # MB
        
        # 检查转录文件
        srt_file = f"transcripts/{yt_video_id}.srt"
        txt_file = f"transcripts/{yt_video_id}.txt"
        transcript_exists = os.path.exists(srt_file) and os.path.exists(txt_file)
        
        # 检查报告文件
        import glob
        safe_title = "".join(c for c in (video_title or yt_video_id) if c.isalnum() or c in (' ', '-', '_')).rstrip()
        report_pattern = f"reports/{safe_title}*.html"
        report_files = glob.glob(report_pattern)
        report_exists = len(report_files) > 0
        
        return {
            'mp3_exists': mp3_exists,
            'mp3_size': round(mp3_size, 2) if mp3_exists else 0,
            'transcript_exists': transcript_exists,
            'report_exists': report_exists
        }
    except:
        return {
            'mp3_exists': False,
            'mp3_size': 0,
            'transcript_exists': False,
            'report_exists': False
        }

@app.route('/report/<filename>')
def view_report(filename):
    """查看简报"""
    return send_from_directory('reports', filename)

@app.route('/api/health')
def health_check():
    """健康检查端点，用于 Vercel 验证后端状态"""
    try:
        import torch
        gpu_available = torch.cuda.is_available()
        gpu_name = torch.cuda.get_device_name(0) if gpu_available else None
    except ImportError:
        gpu_available = False
        gpu_name = None

    return jsonify({
        'status': 'ok',
        'service': 'tldw-backend',
        'gpu_available': gpu_available,
        'gpu_name': gpu_name
    })

@app.route('/api/videos')
def api_videos():
    """API: 获取所有视频列表"""
    videos = db.get_all_videos()
    return jsonify([{
        'id': v[0],
        'url': v[1],
        'title': v[2],
        'report_filename': v[3],
        'status': v[4],
        'created_at': v[5],
        'completed_at': v[6]
    } for v in videos])

@app.route('/api/logs/<int:video_id>')
def get_video_logs(video_id):
    """获取特定视频的处理日志"""
    try:
        # 获取处理器的日志
        if hasattr(processor, 'log_messages'):
            logs = processor.get_logs()
            return jsonify({'success': True, 'logs': logs})
        else:
            return jsonify({'success': False, 'logs': '暂无日志信息'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/delete/<int:video_id>/<delete_type>', methods=['DELETE'])
def delete_video_files(video_id, delete_type):
    """删除视频相关文件"""
    try:
        # 获取视频信息
        video_info = db.get_video_info(video_id)
        if not video_info:
            return jsonify({'error': '视频记录不存在'}), 404
        
        youtube_url = video_info['youtube_url']
        video_title = video_info['video_title']
        report_filename = video_info['report_filename']
        
        # 提取视频ID用于文件名，处理无效链接
        try:
            yt_video_id = processor.extract_video_id(youtube_url)
        except ValueError as e:
            app.logger.warning(f"⚠️ 无效的YouTube链接: {youtube_url}, 错误: {str(e)}")
            # 对于无效链接，使用视频标题或URL的一部分作为文件名模式
            if video_title:
                yt_video_id = "".join(c for c in video_title if c.isalnum() or c in (' ', '-', '_')).strip()[:20]
            else:
                # 从URL中提取可能的标识符
                url_parts = youtube_url.split('/')
                yt_video_id = url_parts[-1] if url_parts else 'unknown'
                yt_video_id = "".join(c for c in yt_video_id if c.isalnum() or c in ('-', '_'))[:20]
            
            if not yt_video_id:
                yt_video_id = f"invalid_{video_id}"
            
            app.logger.info(f"🔧 使用替代文件名模式: {yt_video_id}")
        
        deleted_files = []
        
        if delete_type == 'download':
            # 删除下载的音频文件
            mp3_file = f"downloads/{yt_video_id}.mp3"
            if os.path.exists(mp3_file):
                os.remove(mp3_file)
                deleted_files.append('音频文件')
                app.logger.info(f"✅ 删除音频文件: {mp3_file}")
            
            # 同步检查点状态：重置下载检查点
            db.reset_checkpoint(video_id, 'download')
            app.logger.info(f"🔄 已重置下载检查点状态")
        
        elif delete_type == 'transcript':
            # 删除转录文件
            srt_file = f"transcripts/{yt_video_id}.srt"
            txt_file = f"transcripts/{yt_video_id}.txt"
            
            if os.path.exists(srt_file):
                os.remove(srt_file)
                deleted_files.append('SRT转录文件')
                app.logger.info(f"✅ 删除SRT文件: {srt_file}")
            
            if os.path.exists(txt_file):
                os.remove(txt_file)
                deleted_files.append('TXT转录文件')
                app.logger.info(f"✅ 删除TXT文件: {txt_file}")
            
            # 同步检查点状态：重置转录检查点
            db.reset_checkpoint(video_id, 'transcribe')
            app.logger.info(f"🔄 已重置转录检查点状态")
        
        elif delete_type == 'report':
            # 删除简报文件
            if report_filename:
                report_file = f"reports/{report_filename}"
                if os.path.exists(report_file):
                    os.remove(report_file)
                    deleted_files.append('简报文件')
                    app.logger.info(f"✅ 删除简报文件: {report_file}")
            else:
                # 尝试通过标题模式匹配删除
                import glob
                safe_title = "".join(c for c in (video_title or yt_video_id) if c.isalnum() or c in (' ', '-', '_')).rstrip()
                report_pattern = f"reports/{safe_title}*.html"
                report_files = glob.glob(report_pattern)
                for file in report_files:
                    os.remove(file)
                    deleted_files.append(f'简报文件 {os.path.basename(file)}')
                    app.logger.info(f"✅ 删除简报文件: {file}")
            
            # 同步检查点状态：重置简报检查点
            db.reset_checkpoint(video_id, 'report')
            app.logger.info(f"🔄 已重置简报检查点状态")
        
        elif delete_type == 'all':
            # 删除所有文件和数据库记录
            # 1. 删除音频文件
            mp3_file = f"downloads/{yt_video_id}.mp3"
            if os.path.exists(mp3_file):
                os.remove(mp3_file)
                deleted_files.append('音频文件')
            
            # 2. 删除转录文件
            srt_file = f"transcripts/{yt_video_id}.srt"
            txt_file = f"transcripts/{yt_video_id}.txt"
            if os.path.exists(srt_file):
                os.remove(srt_file)
                deleted_files.append('SRT转录文件')
            if os.path.exists(txt_file):
                os.remove(txt_file)
                deleted_files.append('TXT转录文件')
            
            # 3. 删除简报文件
            if report_filename:
                report_file = f"reports/{report_filename}"
                if os.path.exists(report_file):
                    os.remove(report_file)
                    deleted_files.append('简报文件')
            else:
                import glob
                safe_title = "".join(c for c in (video_title or yt_video_id) if c.isalnum() or c in (' ', '-', '_')).rstrip()
                report_pattern = f"reports/{safe_title}*.html"
                report_files = glob.glob(report_pattern)
                for file in report_files:
                    os.remove(file)
                    deleted_files.append(f'简报文件 {os.path.basename(file)}')
            
            # 同步检查点状态：重置所有检查点
            db.reset_checkpoint(video_id, 'download')
            db.reset_checkpoint(video_id, 'transcribe')
            db.reset_checkpoint(video_id, 'report')
            app.logger.info(f"🔄 已重置所有检查点状态")
            
            # 4. 删除数据库记录
            if db.delete_video_record(video_id):
                deleted_files.append('数据库记录')
                app.logger.info(f"✅ 删除数据库记录: video_id={video_id}")
        
        else:
            return jsonify({'error': '无效的删除类型'}), 400
        
        if deleted_files:
            message = f"成功删除: {', '.join(deleted_files)}"
            app.logger.info(f"🗑️ 删除操作完成: {message}")
            return jsonify({'success': True, 'message': message, 'deleted_files': deleted_files})
        else:
            return jsonify({'success': True, 'message': '没有找到需要删除的文件', 'deleted_files': []})
    
    except Exception as e:
        app.logger.error(f"❌ 删除操作失败: {str(e)}")
        import traceback
        app.logger.error(f"详细错误堆栈:\n{traceback.format_exc()}")
        return jsonify({'error': f'删除失败: {str(e)}'}), 500

@app.route('/api/translate/<int:video_id>', methods=['POST'])
def translate_video(video_id):
    """翻译视频字幕"""
    try:
        data = request.json
        target_language = data.get('target_language', 'en')
        source_language = data.get('source_language')  # 可选，自动检测
        
        app.logger.info(f"🌐 开始翻译视频 {video_id} 到 {target_language}")
        
        # 执行翻译
        translated_text = processor.translate_transcript(video_id, target_language, source_language)
        
        # 获取可用翻译列表
        translations = processor.get_available_translations(video_id)
        
        return jsonify({
            'success': True, 
            'message': '翻译完成',
            'translated_text': translated_text,
            'available_translations': translations
        })
        
    except Exception as e:
        app.logger.error(f"❌ 翻译失败: {str(e)}")
        return jsonify({'error': f'翻译失败: {str(e)}'}), 500

@app.route('/api/translations/<int:video_id>')
def get_video_translations(video_id):
    """获取视频的可用翻译"""
    try:
        translations = processor.get_available_translations(video_id)
        
        # 获取语言信息
        lang_info = db.get_language_info(video_id)
        
        return jsonify({
            'success': True,
            'translations': translations,
            'language_info': lang_info
        })
        
    except Exception as e:
        app.logger.error(f"❌ 获取翻译列表失败: {str(e)}")
        return jsonify({'error': f'获取翻译列表失败: {str(e)}'}), 500

@app.route('/api/translation/<int:video_id>/<language>')
def get_translation_text(video_id, language):
    """获取特定语言的翻译文本"""
    try:
        # 获取视频信息
        video_info = db.get_video_info(video_id)
        if not video_info:
            return jsonify({'error': '视频不存在'}), 404
            
        youtube_url = video_info['youtube_url']
        yt_video_id = processor.extract_video_id(youtube_url)
        
        # 查找翻译文件
        translation_file = f"transcripts/translations/{yt_video_id}_{language}.txt"
        
        if not os.path.exists(translation_file):
            return jsonify({'error': f'没有找到{language}翻译'}), 404
        
        # 读取翻译内容
        with open(translation_file, 'r', encoding='utf-8') as f:
            translation_text = f.read()
        
        return jsonify({
            'success': True,
            'language': language,
            'text': translation_text,
            'language_name': processor.LanguageConfig.get_language_name(language)
        })
        
    except Exception as e:
        app.logger.error(f"❌ 获取翻译文本失败: {str(e)}")
        return jsonify({'error': f'获取翻译文本失败: {str(e)}'}), 500

@app.route('/debug/download')
def debug_download():
    """调试: 直接测试下载功能，不使用线程"""
    
    # 从查询参数获取YouTube URL
    youtube_url = request.args.get('url', 'https://www.youtube.com/watch?v=VcAFEsWyJo8')
    
    try:
        print("="*80)
        print("🔍 DEBUG: 直接在Flask进程中测试下载")
        print(f"📹 URL: {youtube_url}")
        print(f"🐍 Python路径: {sys.executable}")
        print(f"📂 工作目录: {os.getcwd()}")
        print("="*80)
        
        # 直接调用下载方法，不通过数据库和线程
        audio_file, video_title = processor.download_audio(youtube_url, 'debug')
        
        return jsonify({
            'success': True, 
            'message': f'下载成功: {video_title}',
            'audio_file': audio_file,
            'logs': processor.get_logs()
        })
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"❌ DEBUG下载失败: {str(e)}")
        print(f"详细错误: {error_details}")
        
        return jsonify({
            'success': False, 
            'error': str(e),
            'details': error_details,
            'logs': processor.get_logs()
        }), 500

if __name__ == '__main__':
    # 可以通过环境变量PORT设置端口，默认5001
    port = int(os.environ.get('PORT', 5001))
    app.run(debug=True, host='0.0.0.0', port=port)