from flask import Flask, request, render_template, jsonify, send_from_directory
import os
import sqlite3
import threading
from dotenv import load_dotenv
from database import Database
from video_processor import VideoProcessor

load_dotenv()

app = Flask(__name__)
db = Database()
processor = VideoProcessor(db)

@app.route('/')
def index():
    """主页"""
    videos = db.get_all_videos()
    return render_template('index.html', videos=videos)

@app.route('/submit', methods=['POST'])
def submit_url():
    """提交YouTube链接"""
    youtube_url = request.form.get('youtube_url')
    
    if not youtube_url:
        return jsonify({'error': '请提供YouTube链接'}), 400
    
    # 检查URL是否已存在
    existing_video = db.get_video_by_url(youtube_url)
    if existing_video:
        return jsonify({'error': '该视频已经处理过了', 'video_id': existing_video[0]})
    
    try:
        # 插入数据库记录
        video_id = db.insert_video(youtube_url)
        
        # 启动后台处理线程
        thread = threading.Thread(target=processor.process_video, args=(video_id, youtube_url))
        thread.daemon = True
        thread.start()
        
        return jsonify({'success': True, 'video_id': video_id, 'message': '视频处理已开始'})
    
    except Exception as e:
        return jsonify({'error': f'处理失败: {str(e)}'}), 500

@app.route('/status/<int:video_id>')
def get_status(video_id):
    """获取处理状态"""
    with sqlite3.connect(db.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT status, error_message, video_title FROM videos WHERE id=?', (video_id,))
        result = cursor.fetchone()
        
        if result:
            return jsonify({
                'status': result[0], 
                'error': result[1],
                'title': result[2] or '获取标题中...'
            })
        else:
            return jsonify({'error': '视频不存在'}), 404

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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)