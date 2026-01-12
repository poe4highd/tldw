import { createServerSupabaseClient, Video } from '@/lib/supabase-server'
import Link from 'next/link'
import Image from 'next/image'

function formatDuration(seconds: number | null): string {
  if (!seconds) return '--:--'
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return ''
  // YYYYMMDD 格式
  if (dateStr.length === 8) {
    return `${dateStr.slice(0, 4)}-${dateStr.slice(4, 6)}-${dateStr.slice(6, 8)}`
  }
  return dateStr
}

export default async function HomePage() {
  const supabase = await createServerSupabaseClient()

  // 获取所有已完成的视频（公开）
  const { data: videos } = await supabase
    .from('videos')
    .select('*')
    .eq('status', 'completed')
    .order('completed_at', { ascending: false })
    .limit(50)

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      {/* Hero Section */}
      <section className="text-center mb-12">
        <h1 className="text-4xl font-bold mb-4">
          <span className="text-yt-red">YouTube</span> 视频快速摘要
        </h1>
        <p className="text-gray-400 text-lg mb-6">
          自动提取视频关键要点，节省你的时间
        </p>
        <Link
          href="/dashboard"
          className="inline-block bg-yt-red hover:bg-red-700 text-white font-bold py-3 px-8 rounded-full transition"
        >
          开始使用
        </Link>
      </section>

      {/* Video Grid */}
      <section>
        <h2 className="text-2xl font-bold mb-6">最新分析</h2>

        {videos && videos.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {videos.map((video: Video) => (
              <Link
                key={video.id}
                href={`/report/${video.id}`}
                className="bg-yt-gray rounded-xl overflow-hidden hover:ring-2 hover:ring-yt-blue transition group"
              >
                {/* Thumbnail */}
                <div className="relative aspect-video bg-gray-800">
                  {video.video_id ? (
                    <Image
                      src={`https://i.ytimg.com/vi/${video.video_id}/mqdefault.jpg`}
                      alt={video.video_title || '视频缩略图'}
                      fill
                      className="object-cover"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-gray-500">
                      无缩略图
                    </div>
                  )}
                  {/* Duration Badge */}
                  <span className="absolute bottom-2 right-2 bg-black/80 text-white text-xs px-1.5 py-0.5 rounded">
                    {formatDuration(video.duration)}
                  </span>
                </div>

                {/* Info */}
                <div className="p-3">
                  <h3 className="font-medium text-white line-clamp-2 group-hover:text-yt-blue transition">
                    {video.video_title || '未知标题'}
                  </h3>
                  <p className="text-sm text-gray-400 mt-1">
                    {video.channel_name || '未知频道'}
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    {formatDate(video.publish_date)}
                  </p>
                </div>
              </Link>
            ))}
          </div>
        ) : (
          <div className="text-center py-12 text-gray-500">
            <p>暂无已分析的视频</p>
            <Link href="/dashboard" className="text-yt-blue hover:underline mt-2 inline-block">
              提交你的第一个视频
            </Link>
          </div>
        )}
      </section>
    </div>
  )
}
