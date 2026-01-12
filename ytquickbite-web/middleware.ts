import { NextResponse, type NextRequest } from 'next/server'

export async function middleware(request: NextRequest) {
  // 简化的 middleware - 仅做基本的请求转发
  // Supabase 会话刷新在页面级别处理（避免 Edge Runtime 兼容性问题）
  return NextResponse.next()
}

export const config = {
  // 暂时禁用 middleware，只匹配一个不存在的路径
  matcher: ['/_disabled_middleware_path'],
}
