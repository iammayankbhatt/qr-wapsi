/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        navy: '#0E1B3D',
        amber: '#F2A93B',
        teal: '#13A39A',
        paused: '#E5484D',
        panel: '#F1F4F9',
      },
      fontFamily: {
        serif: ['Cambria', 'Georgia', 'serif'],
        sans: ['Inter', 'system-ui', 'Segoe UI', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
