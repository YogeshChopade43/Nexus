/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Driven by CSS variables in index.css so the light/dark theme switch works.
        nexus: {
          bg: 'rgb(var(--nexus-bg) / <alpha-value>)',
          'bg-secondary': 'rgb(var(--nexus-bg-secondary) / <alpha-value>)',
          'bg-tertiary': 'rgb(var(--nexus-bg-tertiary) / <alpha-value>)',
          border: 'rgb(var(--nexus-border) / <alpha-value>)',
          'border-hover': 'rgb(var(--nexus-border-hover) / <alpha-value>)',
          text: 'rgb(var(--nexus-text) / <alpha-value>)',
          'text-secondary': 'rgb(var(--nexus-text-secondary) / <alpha-value>)',
          'text-muted': 'rgb(var(--nexus-text-muted) / <alpha-value>)',
          accent: 'rgb(var(--nexus-accent) / <alpha-value>)',
          'accent-hover': 'rgb(var(--nexus-accent-hover) / <alpha-value>)',
          danger: 'rgb(var(--nexus-danger) / <alpha-value>)',
          'danger-hover': 'rgb(var(--nexus-danger-hover) / <alpha-value>)',
          warning: 'rgb(var(--nexus-warning) / <alpha-value>)',
          info: 'rgb(var(--nexus-info) / <alpha-value>)',
          'accent-dim': 'rgb(var(--nexus-accent) / 0.12)',
        },
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      animation: {
        'fade-in': 'fadeIn 0.2s ease-out',
        'slide-up': 'slideUp 0.3s ease-out',
        'slide-down': 'slideDown 0.3s ease-out',
        'pulse-soft': 'pulseSoft 2s infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        slideDown: {
          '0%': { opacity: '0', transform: 'translateY(-10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        pulseSoft: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.6' },
        },
      },
    },
  },
  plugins: [],
}
