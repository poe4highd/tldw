-- YTQuickBite 初始数据库 Schema
-- 在 Supabase SQL Editor 中执行

-- ============================================
-- 1. 用户配额表
-- ============================================
CREATE TABLE IF NOT EXISTS user_quotas (
  user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  monthly_limit INTEGER DEFAULT 10,
  used_this_month INTEGER DEFAULT 0,
  plan TEXT DEFAULT 'free',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 自动为新用户创建配额记录
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.user_quotas (user_id)
  VALUES (NEW.id);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- ============================================
-- 2. 视频表（核心数据）
-- ============================================
CREATE TABLE IF NOT EXISTS videos (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  youtube_url TEXT NOT NULL,
  video_id TEXT,  -- YouTube 11位视频ID
  video_title TEXT,
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),

  -- 检查点
  download_completed BOOLEAN DEFAULT FALSE,
  transcribe_completed BOOLEAN DEFAULT FALSE,
  report_completed BOOLEAN DEFAULT FALSE,

  -- 文件路径（Supabase Storage 公开 URL）
  audio_file_path TEXT,
  transcript_file_path TEXT,
  report_file_path TEXT,

  -- 元数据
  publish_date TEXT,
  channel_name TEXT,
  duration INTEGER,  -- 秒
  thumbnail_url TEXT,
  whisper_model TEXT,
  detected_language TEXT,
  forced_language TEXT,

  -- 时间戳
  created_at TIMESTAMPTZ DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  error_message TEXT,

  -- 约束：同一用户不能重复提交同一视频
  UNIQUE(user_id, youtube_url)
);

-- 索引优化
CREATE INDEX idx_videos_status ON videos(status);
CREATE INDEX idx_videos_user_id ON videos(user_id);
CREATE INDEX idx_videos_created_at ON videos(created_at DESC);

-- ============================================
-- 3. 系统状态表（单节点监控）
-- ============================================
CREATE TABLE IF NOT EXISTS system_status (
  id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  node_online BOOLEAN DEFAULT FALSE,
  last_heartbeat TIMESTAMPTZ,
  gpu_available BOOLEAN DEFAULT FALSE,
  queue_length INTEGER DEFAULT 0,
  current_task_id UUID REFERENCES videos(id),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 初始化系统状态
INSERT INTO system_status (id, node_online, queue_length)
VALUES (1, FALSE, 0)
ON CONFLICT (id) DO NOTHING;

-- ============================================
-- 4. Row Level Security (RLS) 策略
-- ============================================

-- 启用 RLS
ALTER TABLE user_quotas ENABLE ROW LEVEL SECURITY;
ALTER TABLE videos ENABLE ROW LEVEL SECURITY;
ALTER TABLE system_status ENABLE ROW LEVEL SECURITY;

-- user_quotas: 用户只能查看自己的配额
CREATE POLICY "用户查看自己的配额"
  ON user_quotas FOR SELECT
  USING (auth.uid() = user_id);

-- videos: 登录用户可以插入自己的视频
CREATE POLICY "登录用户可提交视频"
  ON videos FOR INSERT
  WITH CHECK (auth.uid() = user_id);

-- videos: 所有人可以查看已完成的视频（公开浏览）
CREATE POLICY "所有人可查看已完成视频"
  ON videos FOR SELECT
  USING (status = 'completed' OR auth.uid() = user_id);

-- videos: 用户可以删除自己的视频
CREATE POLICY "用户可删除自己的视频"
  ON videos FOR DELETE
  USING (auth.uid() = user_id);

-- system_status: 所有人可查看系统状态
CREATE POLICY "所有人可查看系统状态"
  ON system_status FOR SELECT
  USING (true);

-- ============================================
-- 5. 辅助函数
-- ============================================

-- 增加用户配额使用量
CREATE OR REPLACE FUNCTION increment_quota(uid UUID)
RETURNS void AS $$
BEGIN
  UPDATE user_quotas
  SET used_this_month = used_this_month + 1,
      updated_at = NOW()
  WHERE user_id = uid;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 检查用户配额是否足够
CREATE OR REPLACE FUNCTION check_quota(uid UUID)
RETURNS BOOLEAN AS $$
DECLARE
  quota_record user_quotas%ROWTYPE;
BEGIN
  SELECT * INTO quota_record FROM user_quotas WHERE user_id = uid;
  IF quota_record IS NULL THEN
    RETURN FALSE;
  END IF;
  RETURN quota_record.used_this_month < quota_record.monthly_limit;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 获取待处理队列长度
CREATE OR REPLACE FUNCTION get_queue_length()
RETURNS INTEGER AS $$
BEGIN
  RETURN (SELECT COUNT(*) FROM videos WHERE status = 'pending');
END;
$$ LANGUAGE plpgsql;

-- ============================================
-- 6. 定时任务（需要启用 pg_cron 扩展）
-- ============================================
-- 注意：Supabase 免费版可能不支持 pg_cron
-- 可以改用外部定时任务或 Edge Function 触发

-- 每月重置配额的函数
CREATE OR REPLACE FUNCTION reset_monthly_quotas()
RETURNS void AS $$
BEGIN
  UPDATE user_quotas SET used_this_month = 0, updated_at = NOW();
END;
$$ LANGUAGE plpgsql;

-- ============================================
-- 7. Realtime 启用
-- ============================================
-- 启用 videos 表的 Realtime 功能
ALTER PUBLICATION supabase_realtime ADD TABLE videos;
ALTER PUBLICATION supabase_realtime ADD TABLE system_status;

-- ============================================
-- 8. Storage Buckets 配置
-- ============================================
-- 注意：需要在 Supabase Dashboard → Storage 中手动创建以下 Buckets：
-- 1. reports (公开)
-- 2. transcripts (公开)
--
-- 然后在 SQL Editor 中执行以下策略：

-- 允许服务端上传（使用 service_role key）
-- reports bucket 策略
-- CREATE POLICY "Service role can upload reports"
-- ON storage.objects FOR INSERT
-- TO service_role
-- WITH CHECK (bucket_id = 'reports');

-- CREATE POLICY "Public can read reports"
-- ON storage.objects FOR SELECT
-- TO public
-- USING (bucket_id = 'reports');

-- transcripts bucket 策略
-- CREATE POLICY "Service role can upload transcripts"
-- ON storage.objects FOR INSERT
-- TO service_role
-- WITH CHECK (bucket_id = 'transcripts');

-- CREATE POLICY "Public can read transcripts"
-- ON storage.objects FOR SELECT
-- TO public
-- USING (bucket_id = 'transcripts');
