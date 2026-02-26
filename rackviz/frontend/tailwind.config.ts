import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        rack: {
          bg:       '#0d0d0d',
          frame:    '#1a1a1a',
          device:   '#222',
          port:     '#3a3a3a',
          online:   '#22c55e',
          offline:  '#ef4444',
          uplink:   '#f59e0b',
          reserved: '#6366f1',
          hover:    '#60a5fa',
        },
      },
    },
  },
  plugins: [],
} satisfies Config
