import { createBrowserClient } from '@supabase/ssr'

// 浏览器端客户端
export function createClient() {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL
  const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY

  if (!supabaseUrl || !supabaseAnonKey) {
    throw new Error('Missing Supabase environment variables')
  }

  return createBrowserClient(supabaseUrl, supabaseAnonKey)
}

// 类型定义
export interface Video {
  id: string
  user_id: string
  youtube_url: string
  video_id: string | null
  video_title: string | null
  status: 'pending' | 'processing' | 'completed' | 'failed'
  download_completed: boolean
  transcribe_completed: boolean
  report_completed: boolean
  report_file_path: string | null
  channel_name: string | null
  duration: number | null
  thumbnail_url: string | null
  publish_date: string | null
  created_at: string
  completed_at: string | null
  error_message: string | null
}

export interface UserQuota {
  user_id: string
  monthly_limit: number
  used_this_month: number
  plan: string
}

export interface SystemStatus {
  node_online: boolean
  last_heartbeat: string | null
  gpu_available: boolean
  queue_length: number
}
