"""
YTQuickBite Supabase 客户端
用于本地处理节点与 Supabase 通信
"""

import os
from datetime import datetime
from typing import Optional, Dict, Any, List
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()


class SupabaseClient:
    """Supabase 客户端封装"""

    def __init__(self):
        url = os.environ.get('SUPABASE_URL')
        # 支持新旧两种变量名
        key = os.environ.get('SUPABASE_SECRET_KEY') or os.environ.get('SUPABASE_SERVICE_KEY')

        if not url or not key:
            raise ValueError(
                "缺少 SUPABASE_URL 或 SUPABASE_SECRET_KEY 环境变量\n"
                "请在 .env 文件中配置"
            )

        self.client: Client = create_client(url, key)

    # ============================================
    # 视频任务操作
    # ============================================

    def get_pending_task(self) -> Optional[Dict[str, Any]]:
        """获取一个待处理的任务"""
        result = self.client.table('videos') \
            .select('*') \
            .eq('status', 'pending') \
            .order('created_at') \
            .limit(1) \
            .execute()

        if result.data:
            return result.data[0]
        return None

    def lock_task(self, video_id: str) -> bool:
        """锁定任务，防止重复处理"""
        result = self.client.table('videos') \
            .update({
                'status': 'processing'
            }) \
            .eq('id', video_id) \
            .eq('status', 'pending') \
            .execute()

        return len(result.data) > 0

    def update_task_status(
        self,
        video_id: str,
        status: str,
        error_message: Optional[str] = None,
        **kwargs
    ):
        """更新任务状态"""
        data = {'status': status, **kwargs}

        if status == 'completed':
            data['completed_at'] = datetime.now().isoformat()
        elif status == 'failed' and error_message:
            data['error_message'] = error_message

        self.client.table('videos') \
            .update(data) \
            .eq('id', video_id) \
            .execute()

    def update_checkpoint(
        self,
        video_id: str,
        checkpoint: str,
        completed: bool,
        file_path: Optional[str] = None
    ):
        """更新检查点状态"""
        data = {f'{checkpoint}_completed': completed}

        if file_path:
            data[f'{checkpoint.replace("download", "audio").replace("transcribe", "transcript")}_file_path'] = file_path

        self.client.table('videos') \
            .update(data) \
            .eq('id', video_id) \
            .execute()

    def update_video_meta(
        self,
        video_id: str,
        title: Optional[str] = None,
        channel: Optional[str] = None,
        duration: Optional[int] = None,
        publish_date: Optional[str] = None,
        thumbnail_url: Optional[str] = None,
        youtube_video_id: Optional[str] = None
    ):
        """更新视频元数据"""
        data = {}
        if title:
            data['video_title'] = title
        if channel:
            data['channel_name'] = channel
        if duration:
            data['duration'] = duration
        if publish_date:
            data['publish_date'] = publish_date
        if thumbnail_url:
            data['thumbnail_url'] = thumbnail_url
        if youtube_video_id:
            data['video_id'] = youtube_video_id

        if data:
            self.client.table('videos') \
                .update(data) \
                .eq('id', video_id) \
                .execute()

    def update_language_info(
        self,
        video_id: str,
        detected_language: Optional[str] = None,
        whisper_model: Optional[str] = None
    ):
        """更新语言信息"""
        data = {}
        if detected_language:
            data['detected_language'] = detected_language
        if whisper_model:
            data['whisper_model'] = whisper_model

        if data:
            self.client.table('videos') \
                .update(data) \
                .eq('id', video_id) \
                .execute()

    # ============================================
    # 文件上传
    # ============================================

    def upload_report(self, video_id: str, html_content: str) -> str:
        """上传 HTML 报告到 Supabase Storage"""
        filename = f"reports/{video_id}.html"

        # 上传文件
        self.client.storage \
            .from_('reports') \
            .upload(
                filename,
                html_content.encode('utf-8'),
                {'content-type': 'text/html; charset=utf-8'}
            )

        # 获取公开 URL
        public_url = self.client.storage \
            .from_('reports') \
            .get_public_url(filename)

        # 更新数据库
        self.client.table('videos') \
            .update({
                'report_file_path': public_url,
                'report_completed': True
            }) \
            .eq('id', video_id) \
            .execute()

        return public_url

    def upload_transcript(self, video_id: str, content: str, format: str = 'txt') -> str:
        """上传转录文件到 Supabase Storage"""
        filename = f"transcripts/{video_id}.{format}"

        self.client.storage \
            .from_('transcripts') \
            .upload(
                filename,
                content.encode('utf-8'),
                {'content-type': 'text/plain; charset=utf-8'}
            )

        public_url = self.client.storage \
            .from_('transcripts') \
            .get_public_url(filename)

        if format == 'txt':
            self.client.table('videos') \
                .update({
                    'transcript_file_path': public_url,
                    'transcribe_completed': True
                }) \
                .eq('id', video_id) \
                .execute()

        return public_url

    # ============================================
    # 系统状态
    # ============================================

    def send_heartbeat(self, gpu_available: bool = False, current_task_id: Optional[str] = None):
        """发送心跳"""
        queue_length = self.get_queue_length()

        self.client.table('system_status') \
            .upsert({
                'id': 1,
                'node_online': True,
                'last_heartbeat': datetime.now().isoformat(),
                'gpu_available': gpu_available,
                'queue_length': queue_length,
                'current_task_id': current_task_id,
                'updated_at': datetime.now().isoformat()
            }) \
            .execute()

    def set_offline(self):
        """标记节点离线"""
        self.client.table('system_status') \
            .update({
                'node_online': False,
                'current_task_id': None,
                'updated_at': datetime.now().isoformat()
            }) \
            .eq('id', 1) \
            .execute()

    def get_queue_length(self) -> int:
        """获取待处理队列长度"""
        result = self.client.table('videos') \
            .select('id', count='exact') \
            .eq('status', 'pending') \
            .execute()

        return result.count or 0

    # ============================================
    # 用户配额
    # ============================================

    def get_user_quota(self, user_id: str) -> Optional[Dict[str, Any]]:
        """获取用户配额"""
        result = self.client.table('user_quotas') \
            .select('*') \
            .eq('user_id', user_id) \
            .single() \
            .execute()

        return result.data

    def increment_user_quota(self, user_id: str):
        """增加用户使用量"""
        self.client.rpc('increment_quota', {'uid': user_id}).execute()

    def check_user_quota(self, user_id: str) -> bool:
        """检查用户配额是否足够"""
        result = self.client.rpc('check_quota', {'uid': user_id}).execute()
        return result.data


# 单例模式
_client: Optional[SupabaseClient] = None


def get_supabase_client() -> SupabaseClient:
    """获取 Supabase 客户端单例"""
    global _client
    if _client is None:
        _client = SupabaseClient()
    return _client
