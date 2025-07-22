import sqlite3
import os
from datetime import datetime

class Database:
    def __init__(self, db_path='database.db'):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        """初始化数据库表"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 创建videos表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS videos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    youtube_url TEXT NOT NULL UNIQUE,
                    video_title TEXT,
                    report_filename TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME,
                    error_message TEXT
                )
            ''')
            
            # 创建reports表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER REFERENCES videos(id),
                    summary TEXT,
                    key_points TEXT,
                    transcript_file TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()
    
    def insert_video(self, youtube_url, video_title=None):
        """插入新的视频记录"""
        print(f"📊 DATABASE: 准备插入视频记录")
        print(f"   🔗 URL: {youtube_url}")
        print(f"   📝 标题: {video_title}")
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO videos (youtube_url, video_title) VALUES (?, ?)',
                (youtube_url, video_title)
            )
            conn.commit()
            video_id = cursor.lastrowid
            print(f"✅ DATABASE: 视频记录插入成功，ID: {video_id}")
            return video_id
    
    def update_video_status(self, video_id, status, error_message=None):
        """更新视频处理状态"""
        print(f"📊 DATABASE: 更新视频状态")
        print(f"   🆔 video_id: {video_id}")
        print(f"   📊 status: {status}")
        print(f"   ❌ error_message: {error_message}")
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if status == 'completed':
                cursor.execute(
                    'UPDATE videos SET status=?, completed_at=?, error_message=? WHERE id=?',
                    (status, datetime.now(), error_message, video_id)
                )
            else:
                cursor.execute(
                    'UPDATE videos SET status=?, error_message=? WHERE id=?',
                    (status, error_message, video_id)
                )
            conn.commit()
            print(f"✅ DATABASE: 状态更新完成")
    
    def update_report_filename(self, video_id, filename):
        """更新简报文件名"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE videos SET report_filename=? WHERE id=?',
                (filename, video_id)
            )
            conn.commit()
    
    def get_video_by_url(self, youtube_url):
        """根据URL获取视频记录"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM videos WHERE youtube_url=?', (youtube_url,))
            return cursor.fetchone()
    
    def get_all_videos(self):
        """获取所有视频记录"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM videos ORDER BY created_at DESC')
            return cursor.fetchall()
    
    def get_connection(self):
        """获取数据库连接"""
        return sqlite3.connect(self.db_path)