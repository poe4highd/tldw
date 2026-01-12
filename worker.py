#!/usr/bin/env python3
"""
YTQuickBite 本地处理节点 Worker
从 Supabase 拉取任务，本地处理，结果上传回 Supabase
"""

import os
import sys
import time
import signal
import threading
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# 导入现有模块
from supabase_client import get_supabase_client
from video_processor import VideoProcessor

# 配置（可通过环境变量覆盖）
POLL_INTERVAL = int(os.environ.get('WORKER_POLL_INTERVAL', 5))
HEARTBEAT_INTERVAL = int(os.environ.get('WORKER_HEARTBEAT_INTERVAL', 30))

# 全局状态
running = True
current_task_id = None


def signal_handler(sig, frame):
    """优雅退出"""
    global running
    print("\n收到退出信号，正在优雅关闭...")
    running = False


def check_gpu():
    """检查 GPU 是否可用"""
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


def heartbeat_thread():
    """心跳线程"""
    client = get_supabase_client()
    gpu_available = check_gpu()

    while running:
        try:
            client.send_heartbeat(
                gpu_available=gpu_available,
                current_task_id=current_task_id
            )
        except Exception as e:
            print(f"[心跳] 发送失败: {e}")

        # 分段睡眠，以便快速响应退出信号
        for _ in range(HEARTBEAT_INTERVAL):
            if not running:
                break
            time.sleep(1)


def process_task(task: dict, processor: VideoProcessor, client):
    """处理单个任务"""
    global current_task_id
    video_id = task['id']
    youtube_url = task['youtube_url']
    current_task_id = video_id

    print(f"\n{'='*60}")
    print(f"[任务] 开始处理: {video_id}")
    print(f"[URL] {youtube_url}")
    print(f"{'='*60}")

    try:
        # 使用现有的处理器处理视频
        # 但需要修改为上传到 Supabase 而不是本地存储
        result = processor.process_video_for_supabase(video_id, youtube_url, client)

        if result.get('success'):
            print(f"[完成] 任务 {video_id} 处理成功")
        else:
            error = result.get('error', '未知错误')
            print(f"[失败] 任务 {video_id} 处理失败: {error}")
            client.update_task_status(video_id, 'failed', error_message=error)

    except Exception as e:
        error_msg = str(e)
        print(f"[错误] 任务 {video_id} 异常: {error_msg}")
        client.update_task_status(video_id, 'failed', error_message=error_msg)

    finally:
        current_task_id = None


def main():
    """主循环"""
    global running

    print("="*60)
    print("YTQuickBite 本地处理节点")
    print("="*60)

    # 检查环境
    gpu_available = check_gpu()
    print(f"[环境] GPU 可用: {gpu_available}")

    # 初始化
    try:
        client = get_supabase_client()
        print("[Supabase] 连接成功")
    except Exception as e:
        print(f"[错误] Supabase 连接失败: {e}")
        sys.exit(1)

    processor = VideoProcessor()
    print("[处理器] 初始化完成")

    # 注册信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 启动心跳线程
    heartbeat = threading.Thread(target=heartbeat_thread, daemon=True)
    heartbeat.start()
    print("[心跳] 线程已启动")

    print(f"\n[就绪] 开始轮询任务 (间隔 {POLL_INTERVAL}s)...\n")

    # 主循环
    while running:
        try:
            # 获取待处理任务
            task = client.get_pending_task()

            if task:
                # 尝试锁定任务
                if client.lock_task(task['id']):
                    process_task(task, processor, client)
                else:
                    print(f"[跳过] 任务 {task['id']} 已被其他节点锁定")
            else:
                # 无任务，等待
                pass

        except Exception as e:
            print(f"[错误] 轮询异常: {e}")

        # 等待下一次轮询
        for _ in range(POLL_INTERVAL):
            if not running:
                break
            time.sleep(1)

    # 清理
    print("\n[关闭] 正在标记节点离线...")
    try:
        client.set_offline()
    except Exception:
        pass

    print("[完成] Worker 已退出")


if __name__ == '__main__':
    main()
