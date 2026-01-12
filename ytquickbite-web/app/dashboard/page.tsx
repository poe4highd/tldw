'use client'

import { useEffect, useState } from 'react'
import { createClient, Video, UserQuota, SystemStatus } from '@/lib/supabase-browser'
import { User } from '@supabase/supabase-js'

// 访客账号配置 - 需要在 Supabase 中创建此用户
const GUEST_EMAIL = 'guest@ytquickbite.local'
const GUEST_PASSWORD = 'guest123456'

export default function DashboardPage() {
  const [user, setUser] = useState<User | null>(null)
  const [quota, setQuota] = useState<UserQuota | null>(null)
  const [videos, setVideos] = useState<Video[]>([])
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [url, setUrl] = useState('')
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  const supabase = createClient()

  useEffect(() => {
    loadData()

    // 订阅视频状态变化
    const channel = supabase
      .channel('video-updates')
      .on('postgres_changes', {
        event: '*',
        schema: 'public',
        table: 'videos',
      }, () => {
        loadMyVideos()
      })
      .subscribe()

    return () => {
      supabase.removeChannel(channel)
    }
  }, [])

  async function loadData() {
    setLoading(true)

    // 获取用户
    const { data: { user } } = await supabase.auth.getUser()
    setUser(user)

    if (user) {
      // 获取配额
      const { data: quotaData } = await supabase
        .from('user_quotas')
        .select('*')
        .eq('user_id', user.id)
        .single()
      setQuota(quotaData)

      // 获取我的视频
      await loadMyVideos()
    }

    // 获取系统状态
    const { data: status } = await supabase
      .from('system_status')
      .select('*')
      .eq('id', 1)
      .single()
    setSystemStatus(status)

    setLoading(false)
  }

  async function loadMyVideos() {
    if (!user) return
    const { data } = await supabase
      .from('videos')
      .select('*')
      .eq('user_id', user.id)
      .order('created_at', { ascending: false })
    setVideos(data || [])
  }

  async function handleLogin(provider: 'google' | 'github') {
    await supabase.auth.signInWithOAuth({
      provider,
      options: {
        redirectTo: `${window.location.origin}/auth/callback`,
      },
    })
  }

  // 访客登录 - 使用预设的访客账号
  async function handleGuestLogin() {
    setLoading(true)
    try {
      const { error } = await supabase.auth.signInWithPassword({
        email: GUEST_EMAIL,
        password: GUEST_PASSWORD,
      })
      if (error) {
        console.error('访客登录失败:', error.message)
        setMessage({ type: 'error', text: '访客登录失败，请稍后重试' })
        setLoading(false)
      } else {
        // 登录成功后重新加载数据
        await loadData()
      }
    } catch (err) {
      console.error('访客登录异常:', err)
      setMessage({ type: 'error', text: '访客登录失败' })
      setLoading(false)
    }
  }

  async function handleLogout() {
    await supabase.auth.signOut()
    setUser(null)
    setQuota(null)
    setVideos([])
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!user || !url.trim()) return

    // 检查配额
    if (quota && quota.used_this_month >= quota.monthly_limit) {
      setMessage({ type: 'error', text: '本月配额已用完' })
      return
    }

    setSubmitting(true)
    setMessage(null)

    try {
      // 插入视频
      const { error } = await supabase
        .from('videos')
        .insert({
          user_id: user.id,
          youtube_url: url.trim(),
        })

      if (error) {
        if (error.code === '23505') {
          setMessage({ type: 'error', text: '该视频已经提交过了' })
        } else {
          throw error
        }
      } else {
        // 增加配额使用量
        await supabase.rpc('increment_quota', { uid: user.id })
        setMessage({ type: 'success', text: '提交成功！视频正在处理队列中' })
        setUrl('')
        loadData()
      }
    } catch (err: any) {
      setMessage({ type: 'error', text: err.message || '提交失败' })
    } finally {
      setSubmitting(false)
    }
  }

  function getStatusBadge(status: string) {
    switch (status) {
      case 'pending':
        return <span className="px-2 py-1 bg-yellow-600/20 text-yellow-400 rounded text-sm">排队中</span>
      case 'processing':
        return <span className="px-2 py-1 bg-blue-600/20 text-blue-400 rounded text-sm animate-pulse">处理中</span>
      case 'completed':
        return <span className="px-2 py-1 bg-green-600/20 text-green-400 rounded text-sm">已完成</span>
      case 'failed':
        return <span className="px-2 py-1 bg-red-600/20 text-red-400 rounded text-sm">失败</span>
      default:
        return <span className="px-2 py-1 bg-gray-600/20 text-gray-400 rounded text-sm">{status}</span>
    }
  }

  // 判断当前用户是否是访客
  const isGuest = user?.email === GUEST_EMAIL

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-12 text-center">
        <div className="animate-spin w-8 h-8 border-2 border-yt-blue border-t-transparent rounded-full mx-auto"></div>
        <p className="text-gray-400 mt-4">加载中...</p>
      </div>
    )
  }

  // 未登录
  if (!user) {
    return (
      <div className="max-w-md mx-auto px-4 py-12">
        <div className="bg-yt-gray rounded-xl p-8 text-center">
          <h1 className="text-2xl font-bold mb-6">登录 YTQuickBite</h1>
          <p className="text-gray-400 mb-8">登录后可以提交视频进行分析</p>

          {/* 错误消息 */}
          {message && message.type === 'error' && (
            <div className="mb-4 p-3 rounded-lg bg-red-900/20 text-red-400 text-sm">
              {message.text}
            </div>
          )}

          <div className="space-y-3">
            {/* 访客快速体验按钮 */}
            <button
              onClick={handleGuestLogin}
              className="w-full flex items-center justify-center gap-3 bg-yt-red text-white py-3 px-4 rounded-lg font-medium hover:bg-red-700 transition"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              快速体验（无需注册）
            </button>

            <div className="relative my-4">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-gray-700"></div>
              </div>
              <div className="relative flex justify-center text-sm">
                <span className="px-2 bg-yt-gray text-gray-500">或使用账号登录</span>
              </div>
            </div>

            <button
              onClick={() => handleLogin('google')}
              className="w-full flex items-center justify-center gap-3 bg-white text-gray-800 py-3 px-4 rounded-lg font-medium hover:bg-gray-100 transition"
            >
              <svg className="w-5 h-5" viewBox="0 0 24 24">
                <path fill="currentColor" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
              </svg>
              使用 Google 登录
            </button>

            <button
              onClick={() => handleLogin('github')}
              className="w-full flex items-center justify-center gap-3 bg-gray-800 text-white py-3 px-4 rounded-lg font-medium hover:bg-gray-700 transition border border-gray-600"
            >
              <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
                <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
              </svg>
              使用 GitHub 登录
            </button>
          </div>
        </div>
      </div>
    )
  }

  // 已登录
  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      {/* 用户信息 */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold">
            {isGuest ? '访客模式' : `你好，${user.email?.split('@')[0]}`}
          </h1>
          {quota && (
            <p className="text-gray-400 mt-1">
              本月已使用 {quota.used_this_month} / {quota.monthly_limit} 次
            </p>
          )}
          {isGuest && (
            <p className="text-yellow-500 text-sm mt-1">
              访客数据可能被清理，建议登录保存记录
            </p>
          )}
        </div>
        <button
          onClick={handleLogout}
          className="text-gray-400 hover:text-white transition"
        >
          退出{isGuest ? '访客' : '登录'}
        </button>
      </div>

      {/* 系统状态 */}
      {systemStatus && (
        <div className={`mb-6 p-4 rounded-lg ${systemStatus.node_online ? 'bg-green-900/20' : 'bg-red-900/20'}`}>
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${systemStatus.node_online ? 'bg-green-500' : 'bg-red-500'}`}></span>
            <span className={systemStatus.node_online ? 'text-green-400' : 'text-red-400'}>
              处理节点{systemStatus.node_online ? '在线' : '离线'}
            </span>
            {systemStatus.node_online && (
              <span className="text-gray-500 text-sm ml-2">
                队列: {systemStatus.queue_length} 个任务
                {systemStatus.gpu_available && ' | GPU 加速'}
              </span>
            )}
          </div>
        </div>
      )}

      {/* 提交表单 */}
      <form onSubmit={handleSubmit} className="mb-8">
        <div className="flex gap-3">
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="粘贴 YouTube 视频链接..."
            className="flex-1 bg-yt-gray border border-gray-700 rounded-lg px-4 py-3 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-yt-blue"
            disabled={submitting || !!(quota && quota.used_this_month >= quota.monthly_limit)}
          />
          <button
            type="submit"
            disabled={submitting || !url.trim() || !!(quota && quota.used_this_month >= quota.monthly_limit)}
            className="bg-yt-red hover:bg-red-700 disabled:bg-gray-700 disabled:cursor-not-allowed text-white font-bold py-3 px-6 rounded-lg transition"
          >
            {submitting ? '提交中...' : '分析'}
          </button>
        </div>
      </form>

      {/* 消息 */}
      {message && (
        <div className={`mb-6 p-4 rounded-lg ${message.type === 'success' ? 'bg-green-900/20 text-green-400' : 'bg-red-900/20 text-red-400'}`}>
          {message.text}
        </div>
      )}

      {/* 我的视频 */}
      <section>
        <h2 className="text-xl font-bold mb-4">我的视频</h2>

        {videos.length > 0 ? (
          <div className="space-y-3">
            {videos.map((video) => (
              <div
                key={video.id}
                className="bg-yt-gray rounded-lg p-4 flex items-center justify-between"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-white font-medium truncate">
                    {video.video_title || video.youtube_url}
                  </p>
                  {video.channel_name && (
                    <p className="text-gray-500 text-sm">{video.channel_name}</p>
                  )}
                </div>
                <div className="flex items-center gap-4 ml-4">
                  {getStatusBadge(video.status)}
                  {video.status === 'completed' && video.report_file_path && (
                    <a
                      href={`/report/${video.id}`}
                      className="text-yt-blue hover:underline text-sm"
                    >
                      查看报告
                    </a>
                  )}
                  {video.status === 'failed' && video.error_message && (
                    <span className="text-red-400 text-sm truncate max-w-[200px]" title={video.error_message}>
                      {video.error_message}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-gray-500 text-center py-8">
            还没有提交过视频
          </p>
        )}
      </section>
    </div>
  )
}
