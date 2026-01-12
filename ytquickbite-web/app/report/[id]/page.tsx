import { createServerSupabaseClient } from '@/lib/supabase'
import { notFound, redirect } from 'next/navigation'

interface Props {
  params: Promise<{ id: string }>
}

export default async function ReportPage({ params }: Props) {
  const { id } = await params
  const supabase = await createServerSupabaseClient()

  // 获取视频信息
  const { data: video, error } = await supabase
    .from('videos')
    .select('*')
    .eq('id', id)
    .single()

  if (error || !video) {
    notFound()
  }

  // 如果报告还没完成
  if (video.status !== 'completed' || !video.report_file_path) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-12 text-center">
        <h1 className="text-2xl font-bold mb-4">报告尚未生成</h1>
        <p className="text-gray-400 mb-4">
          视频状态: {video.status === 'pending' ? '排队中' : video.status === 'processing' ? '处理中' : video.status}
        </p>
        {video.status === 'failed' && video.error_message && (
          <p className="text-red-400">{video.error_message}</p>
        )}
        <a href="/dashboard" className="text-yt-blue hover:underline">
          返回仪表板
        </a>
      </div>
    )
  }

  // 重定向到 Supabase Storage 的报告 URL
  redirect(video.report_file_path)
}
