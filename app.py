from flask import Flask, request, render_template, jsonify, send_from_directory
import os
import sys
import sqlite3
import threading
import logging
from dotenv import load_dotenv
from database import Database
from video_processor import VideoProcessor

load_dotenv()

# 配置详细日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

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
app.logger.setLevel(logging.DEBUG)

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

@app.route('/')
def index():
    """主页"""
    videos = db.get_all_videos()
    return render_template('index.html', videos=videos)

@app.route('/submit', methods=['POST'])
def submit_url():
    """提交YouTube链接"""
    app.logger.info("🔵 开始处理/submit请求")
    
    youtube_url = request.form.get('youtube_url')
    app.logger.info(f"📹 收到YouTube URL: {youtube_url}")
    
    if not youtube_url:
        app.logger.warning("❌ 未提供YouTube链接")
        return jsonify({'error': '请提供YouTube链接'}), 400
    
    # 检查URL是否已存在
    app.logger.info("🔍 检查URL是否已存在...")
    existing_video = db.get_video_by_url(youtube_url)
    if existing_video:
        video_id, url, title, report_filename, status, created_at, completed_at, error_message = existing_video
        app.logger.info(f"⚠️ 视频已存在，ID: {video_id}, 状态: {status}")
        
        # 如果状态是completed且有文件，拒绝重复处理
        if status == 'completed' and report_filename:
            app.logger.info("✅ 视频已成功处理，拒绝重复处理")
            return jsonify({'error': '该视频已经处理过了', 'video_id': video_id})
        
        # 如果状态是failed或processing，允许重新处理
        if status in ['failed', 'processing']:
            app.logger.info(f"🔄 视频状态为{status}，允许重新处理")
            video_id = existing_video[0]  # 使用现有的video_id
        else:
            app.logger.info("⚠️ 视频状态不明确，拒绝处理")
            return jsonify({'error': '该视频已经处理过了', 'video_id': video_id})
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