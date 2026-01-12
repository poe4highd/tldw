import { NextResponse, type NextRequest } from 'next/server'

export async function middleware(request: NextRequest) {
  // 简化的 middleware - 仅做基本的请求转发
  // Supabase 会话刷新在页面级别处理（避免 Edge Runtime 兼容性问题）
  return NextResponse.next()
}

export const config = {
  matcher: [
    /*
     * 匹配所有路径除了：
     * - _next/static (静态文件)
     * - _next/image (图片优化)
     * - favicon.ico (浏览器图标)
     * - 公共文件夹
     */
    '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
  ],
}
