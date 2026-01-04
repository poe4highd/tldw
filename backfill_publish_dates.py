#!/usr/bin/env python3
"""
为现有视频回填发布日期、频道名和时长信息

使用方法:
    python backfill_publish_dates.py

这个脚本会:
1. 查找所有没有 publish_date 的已完成视频
2. 使用 yt-dlp 获取视频元数据
3. 更新数据库中的 publish_date, channel_name, duration 字段
"""

import sqlite3
import yt_dlp
import re


def extract_video_id(youtube_url):
    """从YouTube URL中提取视频ID"""
    patterns = [
        r'(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'(?:embed/|shorts/)([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$'
    ]
    for pattern in patterns:
        match = re.search(pattern, youtube_url)
        if match:
            return match.group(1)
    return None


def get_video_info(youtube_url):
    """获取视频信息"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            return {
                'upload_date': info.get('upload_date'),  # YYYYMMDD
                'channel_name': info.get('channel') or info.get('uploader'),
                'duration': info.get('duration'),
                'title': info.get('title'),
            }
    except Exception as e:
        print(f"  ❌ 获取信息失败: {e}")
        return None


def backfill_publish_dates():
    """回填所有缺失的发布日期"""
    db_path = 'database.db'

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # 查找所有没有 publish_date 的已完成视频
        cursor.execute('''
            SELECT id, youtube_url, video_title
            FROM videos
            WHERE status = 'completed'
              AND (publish_date IS NULL OR publish_date = '')
        ''')
        videos = cursor.fetchall()

        if not videos:
            print("✅ 所有视频都已有发布日期信息，无需回填")
            return

        print(f"📋 找到 {len(videos)} 个需要回填的视频\n")

        success_count = 0
        fail_count = 0

        for video_id, youtube_url, title in videos:
            print(f"🔄 处理视频 #{video_id}: {title or '未知标题'}")
            print(f"   URL: {youtube_url}")

            # 验证URL
            yt_video_id = extract_video_id(youtube_url)
            if not yt_video_id:
                print(f"  ⚠️ 无效的YouTube URL，跳过")
                fail_count += 1
                continue

            # 获取视频信息
            info = get_video_info(youtube_url)
            if not info:
                fail_count += 1
                continue

            # 更新数据库
            cursor.execute('''
                UPDATE videos
                SET publish_date = ?,
                    channel_name = ?,
                    duration = ?
                WHERE id = ?
            ''', (info['upload_date'], info['channel_name'], info['duration'], video_id))

            print(f"  ✅ 已更新:")
            if info['upload_date']:
                date_str = f"{info['upload_date'][:4]}-{info['upload_date'][4:6]}-{info['upload_date'][6:8]}"
                print(f"     📅 发布日期: {date_str}")
            if info['channel_name']:
                print(f"     📺 频道名称: {info['channel_name']}")
            if info['duration']:
                minutes = info['duration'] // 60
                seconds = info['duration'] % 60
                print(f"     ⏱️ 视频时长: {minutes}:{seconds:02d}")

            success_count += 1
            print()

        conn.commit()

        print("=" * 50)
        print(f"📊 回填完成:")
        print(f"   ✅ 成功: {success_count}")
        print(f"   ❌ 失败: {fail_count}")
        print("=" * 50)


if __name__ == '__main__':
    print("=" * 50)
    print("🔄 开始回填视频发布日期信息")
    print("=" * 50)
    print()
    backfill_publish_dates()
