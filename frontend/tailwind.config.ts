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
        'on-dark': '#FBFCFB',                // text on chrome, pine and loss/gain fills
        'on-gold': '#14201C',                // text on a gold button
        'pine-deep': themed('pine-deep-fill'),  // the highlighted card and sign-in panel
        'pine': themed('pine-fill'),            // buttons, the selected pill
        'gain': '#2E8B6B',
        'loss': '#C2703D',
        'gold': '#C9A24B',
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
