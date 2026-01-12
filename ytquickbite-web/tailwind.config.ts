import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        'yt-red': '#ff0000',
        'yt-dark': '#0f0f0f',
        'yt-gray': '#272727',
        'yt-light-gray': '#aaaaaa',
        'yt-blue': '#3ea6ff',
      },
    },
  },
  plugins: [],
}

export default config
