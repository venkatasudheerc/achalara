import type { Config } from 'tailwindcss'

// A colour that follows the theme: its channels live in a CSS variable set in
// src/index.css, once for light and once under `.dark`.
const themed = (name: string) => `rgb(var(--${name}) / <alpha-value>)`

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Follow the theme.
        'paper': themed('paper'),            // the page
        'surface': themed('surface'),        // cards, inputs, tables
        'mist': themed('mist'),              // tinted panels
        'summit-ink': themed('ink'),         // body text
        'stone': themed('stone'),            // secondary text, hairlines
        'chrome': themed('chrome'),          // header and sidebar: dark in both themes
        // The same in both themes (pine and pine-deep shift a little in dark).
        'on-dark': themed('on-dark'),        // text on chrome, pine and loss/gain fills
        'on-gold': themed('on-gold'),        // text on a gold button
        'pine-deep': themed('pine-deep-fill'),  // the highlighted card and sign-in panel
        'pine': themed('pine-fill'),            // buttons, the selected pill
        'gain': themed('gain-fill'),
        'loss': themed('loss-fill'),
        'gold': themed('gold'),
        // The new app only (defined under .one-app in src/index.css)
        'line': themed('line'),
        'accent-soft': themed('accent-soft'),
        'k-cash': themed('k-cash'), 'k-cash-bg': themed('k-cash-bg'),
        'k-taxable': themed('k-taxable'), 'k-taxable-bg': themed('k-taxable-bg'),
        'k-retire': themed('k-retire'), 'k-retire-bg': themed('k-retire-bg'),
        'k-kids': themed('k-kids'), 'k-kids-bg': themed('k-kids-bg'),
        'k-bank': themed('k-bank'), 'k-bank-bg': themed('k-bank-bg'),
        'k-owed': themed('k-owed'), 'k-owed-bg': themed('k-owed-bg'),
      },
      // As text and outlines these need to lift off a dark page; as fills
      // (bg-pine, bg-gain, bg-loss) they stay the brand colours above.
      textColor: {
        'pine': themed('pine-text'),
        'pine-deep': themed('pine-deep-text'),
        'gain': themed('gain-text'),
        'loss': themed('loss-text'),
      },
      borderColor: {
        'pine': themed('pine-text'),
      },
      fontFamily: {
        display: ['Fraunces', 'Georgia', 'serif'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'Menlo', 'monospace'],
      },
      borderRadius: {
        card: '10px',
        btn: '8px',
      },
      spacing: {
        '4': '4px',
        '8': '8px',
        '12': '12px',
        '16': '16px',
        '24': '24px',
        '32': '32px',
        '48': '48px',
        '64': '64px',
        '96': '96px',
      },
    },
  },
  plugins: [],
} satisfies Config
