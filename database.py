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
            
            # 数据库迁移：添加whisper_model字段
            self._migrate_db(cursor)
            
            conn.commit()
    
    def _migrate_db(self, cursor):
        """数据库迁移"""
        # 检查现有字段
        cursor.execute("PRAGMA table_info(videos)")
        columns = [column[1] for column in cursor.fetchall()]
        
        # 添加whisper_model字段
        if 'whisper_model' not in columns:
            print("🔄 数据库迁移: 添加whisper_model字段...")
            cursor.execute('ALTER TABLE videos ADD COLUMN whisper_model TEXT')
            print("✅ whisper_model字段添加成功")
        
        # 添加检查点字段
        checkpoint_fields = [
            ('download_completed', 'INTEGER DEFAULT 0'),
            ('transcribe_completed', 'INTEGER DEFAULT 0'), 
            ('report_completed', 'INTEGER DEFAULT 0'),
            ('audio_file_path', 'TEXT'),
            ('transcript_file_path', 'TEXT')
        ]
        
        # 添加多语言支持字段
        multilang_fields = [
            ('detected_language', 'TEXT'),           # 自动检测的语言
            ('forced_language', 'TEXT'),             # 用户强制指定的语言
            ('target_language', 'TEXT DEFAULT "zh"'), # 目标翻译语言
            ('translation_completed', 'INTEGER DEFAULT 0'), # 翻译是否完成
            ('subtitle_quality_score', 'REAL'),      # 字幕质量评分
            ('available_languages', 'TEXT')          # 可用语言列表(JSON格式)
        ]
        
        for field_name, field_type in checkpoint_fields:
            if field_name not in columns:
                print(f"🔄 数据库迁移: 添加{field_name}字段...")
                cursor.execute(f'ALTER TABLE videos ADD COLUMN {field_name} {field_type}')
                print(f"✅ {field_name}字段添加成功")
        
        # 添加多语言字段
        for field_name, field_type in multilang_fields:
            if field_name not in columns:
                print(f"🔄 数据库迁移: 添加多语言字段{field_name}...")
                cursor.execute(f'ALTER TABLE videos ADD COLUMN {field_name} {field_type}')
                print(f"✅ 多语言字段{field_name}添加成功")
        
        # 迁移现有数据：将已完成的视频设置为所有检查点完成
        print("🔄 数据库迁移: 更新现有已完成视频的检查点状态...")
        cursor.execute("""
            UPDATE videos 
            SET download_completed=1, transcribe_completed=1, report_completed=1 
            WHERE status='completed' AND (download_completed IS NULL OR download_completed=0)
        """)
        rows_updated = cursor.rowcount
        if rows_updated > 0:
            print(f"✅ 已更新 {rows_updated} 条已完成视频的检查点状态")
        
        # 迁移现有数据：设置默认语言为中文
        print("🔄 数据库迁移: 设置现有视频的默认语言...")
        cursor.execute("""
            UPDATE videos 
            SET detected_language='zh', target_language='zh'
            WHERE detected_language IS NULL
        """)
        lang_rows_updated = cursor.rowcount
        if lang_rows_updated > 0:
            print(f"✅ 已更新 {lang_rows_updated} 条视频的默认语言设置")
    
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
    
    def update_whisper_model(self, video_id, whisper_model):
        """更新视频使用的Whisper模型"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE videos SET whisper_model=? WHERE id=?',
                (whisper_model, video_id)
            )
            conn.commit()
    
    def get_video_whisper_model(self, video_id):
        """获取视频使用的Whisper模型"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT whisper_model FROM videos WHERE id=?', (video_id,))
            result = cursor.fetchone()
            return result[0] if result else None
    
    def get_connection(self):
        """获取数据库连接"""
        return sqlite3.connect(self.db_path)
    
    def delete_video_record(self, video_id):
        """删除视频记录和相关报告记录"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # 先删除reports表中的相关记录
            cursor.execute('DELETE FROM reports WHERE video_id=?', (video_id,))
            # 再删除videos表中的记录
            cursor.execute('DELETE FROM videos WHERE id=?', (video_id,))
            conn.commit()
            return cursor.rowcount > 0
    
    def get_video_info(self, video_id):
        """获取视频信息用于文件删除"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT youtube_url, video_title, report_filename FROM videos WHERE id=?', (video_id,))
            result = cursor.fetchone()
            if result:
                return {
                    'youtube_url': result[0],
                    'video_title': result[1], 
                    'report_filename': result[2]
                }
            return None
    
    # 检查点相关方法
    def update_checkpoint(self, video_id, checkpoint, status, file_path=None):
        """更新检查点状态"""
        print(f"📊 DATABASE: 更新检查点状态")
        print(f"   🆔 video_id: {video_id}")
        print(f"   🎯 checkpoint: {checkpoint}")
        print(f"   📊 status: {status}")
        print(f"   📁 file_path: {file_path}")
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            if checkpoint == 'download':
                if file_path:
                    cursor.execute(
                        'UPDATE videos SET download_completed=?, audio_file_path=? WHERE id=?',
                        (status, file_path, video_id)
                    )
                else:
                    cursor.execute(
                        'UPDATE videos SET download_completed=? WHERE id=?',
                        (status, video_id)
                    )
            elif checkpoint == 'transcribe':
                if file_path:
                    cursor.execute(
                        'UPDATE videos SET transcribe_completed=?, transcript_file_path=? WHERE id=?',
                        (status, file_path, video_id)
                    )
                else:
                    cursor.execute(
                        'UPDATE videos SET transcribe_completed=? WHERE id=?',
                        (status, video_id)
                    )
            elif checkpoint == 'report':
                cursor.execute(
                    'UPDATE videos SET report_completed=? WHERE id=?',
                    (status, video_id)
                )
            
            conn.commit()
            print(f"✅ DATABASE: 检查点状态更新完成")
    
    def get_checkpoint_status(self, video_id):
        """获取视频的检查点状态"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT download_completed, transcribe_completed, report_completed,
                       audio_file_path, transcript_file_path, report_filename
                FROM videos WHERE id=?
            ''', (video_id,))
            result = cursor.fetchone()
            
            if result:
                return {
                    'download_completed': bool(result[0]) if result[0] is not None else False,
                    'transcribe_completed': bool(result[1]) if result[1] is not None else False,
                    'report_completed': bool(result[2]) if result[2] is not None else False,
                    'audio_file_path': result[3],
                    'transcript_file_path': result[4],
                    'report_filename': result[5]
                }
            return None
    
    def reset_checkpoint(self, video_id, checkpoint):
        """重置特定检查点状态"""
        print(f"📊 DATABASE: 重置检查点状态 - {checkpoint}")
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            if checkpoint == 'download':
                cursor.execute(
                    'UPDATE videos SET download_completed=0, audio_file_path=NULL WHERE id=?',
                    (video_id,)
                )
            elif checkpoint == 'transcribe':
                cursor.execute(
                    'UPDATE videos SET transcribe_completed=0, transcript_file_path=NULL WHERE id=?',
                    (video_id,)
                )
            elif checkpoint == 'report':
                cursor.execute(
                    'UPDATE videos SET report_completed=0, report_filename=NULL WHERE id=?',
                    (video_id,)
                )
            
            conn.commit()
            print(f"✅ DATABASE: 检查点重置完成")
    
    # 多语言相关方法
    def update_language_info(self, video_id, detected_language=None, forced_language=None, target_language=None):
        """更新视频的语言信息"""
        print(f"📊 DATABASE: 更新语言信息 - video_id: {video_id}")
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            update_fields = []
            params = []
            
            if detected_language is not None:
                update_fields.append('detected_language=?')
                params.append(detected_language)
                print(f"   🔍 检测语言: {detected_language}")
            
            if forced_language is not None:
                update_fields.append('forced_language=?')
                params.append(forced_language)
                print(f"   👤 用户指定语言: {forced_language}")
            
            if target_language is not None:
                update_fields.append('target_language=?')
                params.append(target_language)
                print(f"   🎯 目标语言: {target_language}")
            
            if update_fields:
                params.append(video_id)
                cursor.execute(
                    f'UPDATE videos SET {", ".join(update_fields)} WHERE id=?',
                    params
                )
                conn.commit()
                print(f"✅ DATABASE: 语言信息更新完成")
    
    def update_translation_status(self, video_id, completed=True):
        """更新翻译完成状态"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE videos SET translation_completed=? WHERE id=?',
                (1 if completed else 0, video_id)
            )
            conn.commit()
            print(f"✅ DATABASE: 翻译状态更新为 {'完成' if completed else '未完成'}")
    
    def update_subtitle_quality(self, video_id, score):
        """更新字幕质量评分"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE videos SET subtitle_quality_score=? WHERE id=?',
                (score, video_id)
            )
            conn.commit()
            print(f"✅ DATABASE: 字幕质量评分更新为 {score}")
    
    def update_available_languages(self, video_id, languages):
        """更新可用语言列表"""
        import json
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE videos SET available_languages=? WHERE id=?',
                (json.dumps(languages), video_id)
            )
            conn.commit()
            print(f"✅ DATABASE: 可用语言列表更新为 {languages}")
    
    def get_language_info(self, video_id):
        """获取视频的语言信息"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT detected_language, forced_language, target_language, 
                       translation_completed, subtitle_quality_score, available_languages
                FROM videos WHERE id=?
            ''', (video_id,))
            result = cursor.fetchone()
            
            if result:
                import json
                available_languages = []
                if result[5]:
                    try:
                        available_languages = json.loads(result[5])
                    except:
                        available_languages = []
                
                return {
                    'detected_language': result[0],
                    'forced_language': result[1],
                    'target_language': result[2],
                    'translation_completed': bool(result[3]) if result[3] is not None else False,
                    'subtitle_quality_score': result[4],
                    'available_languages': available_languages
                }
            return None