#!/usr/bin/env python3
"""
YouTube下载测试脚本
单独测试YouTube MP3下载功能
"""

import os
import sys
import yt_dlp
import sqlite3
from datetime import datetime

def test_download_strategies(youtube_url):
    """测试多种下载策略"""
    
    strategies = [
        {
            "name": "策略1: 主要方法 (带Cookie和完整Headers)",
            "config": {
                'format': 'bestaudio/best',
                'outtmpl': f'downloads/test_main_%(title)s.%(ext)s',
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
        },
        {
            "name": "策略2: Android客户端",
            "config": {
                'format': 'bestaudio/best',
                'outtmpl': f'downloads/test_android_%(title)s.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'extractor_args': {'youtube': {'player_client': ['android']}},
                'user_agent': 'com.google.android.youtube/17.31.35 (Linux; U; Android 11) gzip',
                'no_warnings': True,
            }
        },
        {
            "name": "策略3: iOS客户端",
            "config": {
                'format': 'bestaudio/best',
                'outtmpl': f'downloads/test_ios_%(title)s.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'extractor_args': {'youtube': {'player_client': ['ios']}},
                'user_agent': 'com.google.ios.youtube/17.31.4 (iPhone; CPU iPhone OS 15_6 like Mac OS X)',
                'no_warnings': True,
            }
        },
        {
            "name": "策略4: 最简配置 (webm格式)",
            "config": {
                'format': 'worst[ext=webm]/worst',
                'outtmpl': f'downloads/test_simple_%(title)s.%(ext)s',
                'no_warnings': True,
                'quiet': False,
            }
        },
        {
            "name": "策略5: 超简化配置",
            "config": {
                'format': 'worst',
                'outtmpl': f'downloads/test_ultra_simple_%(title)s.%(ext)s',
                'no_warnings': True,
                'quiet': False,
            }
        }
    ]
    
    print(f"🎯 开始测试YouTube下载: {youtube_url}")
    print("=" * 80)
    
    for i, strategy in enumerate(strategies, 1):
        print(f"\n📝 {strategy['name']}")
        print("-" * 60)
        
        try:
            with yt_dlp.YoutubeDL(strategy['config']) as ydl:
                # 先获取视频信息
                print("📋 获取视频信息...")
                info = ydl.extract_info(youtube_url, download=False)
                
                print(f"✅ 视频标题: {info.get('title', 'Unknown')}")
                print(f"✅ 视频时长: {info.get('duration', 'Unknown')}秒")
                print(f"✅ 上传者: {info.get('uploader', 'Unknown')}")
                
                # 尝试下载
                print("⬇️  开始下载...")
                ydl.download([youtube_url])
                
                print(f"🎉 策略 {i} 成功！")
                
                # 检查下载的文件
                print("\n📁 检查下载文件:")
                downloads_dir = "downloads"
                if os.path.exists(downloads_dir):
                    files = [f for f in os.listdir(downloads_dir) if f.startswith('test_')]
                    for file in files:
                        file_path = os.path.join(downloads_dir, file)
                        size = os.path.getsize(file_path) / (1024 * 1024)  # MB
                        print(f"  📄 {file} ({size:.2f} MB)")
                
                return True, strategy['name'], info.get('title', 'Unknown')
                
        except Exception as e:
            print(f"❌ 策略 {i} 失败: {str(e)}")
            continue
    
    return False, None, None

def clean_test_files():
    """清理测试文件"""
    downloads_dir = "downloads"
    if os.path.exists(downloads_dir):
        test_files = [f for f in os.listdir(downloads_dir) if f.startswith('test_')]
        for file in test_files:
            file_path = os.path.join(downloads_dir, file)
            try:
                os.remove(file_path)
                print(f"🗑️  删除测试文件: {file}")
            except Exception as e:
                print(f"❌ 无法删除 {file}: {e}")

def main():
    print("🔧 YouTube下载测试工具")
    print("=" * 50)
    
    # 测试URL
    test_url = "https://www.youtube.com/watch?v=VcAFEsWyJo8"
    
    # 确保下载目录存在
    os.makedirs("downloads", exist_ok=True)
    
    # 清理之前的测试文件
    print("🧹 清理之前的测试文件...")
    clean_test_files()
    
    # 开始测试
    success, strategy, title = test_download_strategies(test_url)
    
    print("\n" + "=" * 80)
    if success:
        print(f"🎉 测试成功！")
        print(f"📝 成功策略: {strategy}")
        print(f"🎵 视频标题: {title}")
        print(f"📁 文件保存在: downloads/ 目录")
    else:
        print("❌ 所有策略都失败了")
        print("💡 可能的解决方案:")
        print("   1. 检查网络连接")
        print("   2. 在Firefox中登录YouTube账号")
        print("   3. 尝试使用VPN")
        print("   4. 检查视频是否被地区限制")
    
    print("\n🔍 yt-dlp版本信息:")
    print(f"   版本: {yt_dlp.version.__version__}")
    
    return success

if __name__ == "__main__":
    main()