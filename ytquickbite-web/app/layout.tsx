import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'YTQuickBite - YouTube 视频快速摘要',
  description: '自动提取 YouTube 视频的关键要点和字幕，让你快速了解视频内容',
  robots: {
    index: false,
    follow: false,
    googleBot: {
      index: false,
      follow: false,
    },
  },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="zh-CN">
      <head>
        <meta name="robots" content="noindex, nofollow, noarchive, nosnippet" />
      </head>
      <body className={inter.className}>
        <nav className="bg-yt-gray border-b border-gray-700">
          <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
            <a href="/" className="text-xl font-bold text-white flex items-center gap-2">
              <span className="text-yt-red">YT</span>QuickBite
            </a>
            <div className="flex items-center gap-4">
              <a href="/dashboard" className="text-gray-300 hover:text-white">
                仪表板
              </a>
            </div>
          </div>
        </nav>
        <main>{children}</main>
      </body>
    </html>
  )
}
