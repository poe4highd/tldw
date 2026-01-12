import Link from 'next/link'

export default function NotFound() {
  return (
    <div className="max-w-4xl mx-auto px-4 py-12 text-center">
      <h1 className="text-4xl font-bold mb-4">404</h1>
      <p className="text-gray-400 mb-6">页面不存在</p>
      <Link
        href="/"
        className="inline-block bg-yt-red hover:bg-red-700 text-white font-bold py-2 px-6 rounded-lg transition"
      >
        返回首页
      </Link>
    </div>
  )
}
