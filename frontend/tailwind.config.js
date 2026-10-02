/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: 'var(--color-canvas)',
        'surface-1': 'var(--color-surface-1)',
        'surface-2': 'var(--color-surface-2)',
        'surface-hover': 'var(--color-surface-hover)',
        'border-subtle': 'var(--color-border-subtle)',
        'border-control': 'var(--color-border-control)',
        'text-primary': 'var(--color-text-primary)',
        'text-secondary': 'var(--color-text-secondary)',
        'text-muted': 'var(--color-text-muted)',
        execution: 'var(--color-execution)',
        accepted: 'var(--color-accepted)',
        verified: 'var(--color-verified)',
        attention: 'var(--color-attention)',
        failure: 'var(--color-failure)',
        focus: 'var(--color-focus)',
      },
      fontFamily: {
        sans: ['var(--font-sans)'],
        mono: ['var(--font-mono)'],
      },
    },
  },
  plugins: [],
};
