import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'

// 重新导出类型供服务端组件使用
export type { Video, UserQuota, SystemStatus } from './supabase-browser'

// 服务端客户端（用于 Server Components 和 API Routes）
export async function createServerSupabaseClient() {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL
  const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY

  if (!supabaseUrl || !supabaseAnonKey) {
    throw new Error('Missing Supabase environment variables')
  }

  const cookieStore = await cookies()

  return createServerClient(supabaseUrl, supabaseAnonKey, {
    cookies: {
      getAll() {
        return cookieStore.getAll()
      },
      setAll(cookiesToSet: { name: string; value: string; options?: Record<string, unknown> }[]) {
        try {
          cookiesToSet.forEach(({ name, value, options }) =>
            cookieStore.set(name, value, options)
          )
        } catch {
          // 在 Server Component 中调用时忽略错误
        }
      },
    },
  })
}
