import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

export type Theme = 'light' | 'dark'

/** Where the viewer's choice is kept; index.html reads it before first paint. */
const STORAGE_KEY = 'achalara-theme'

/**
 * Whether viewers may choose light or dark. While false the app is dark for
 * everyone, whatever they chose before or their system prefers, and the
 * switch is not shown. The light theme stays defined so it can come back:
 * set this to true and restore the saved-choice line in index.html.
 */
export const THEME_CHOICE_OFFERED = false

function initialTheme(): Theme {
  if (!THEME_CHOICE_OFFERED) return 'dark'
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'light' || saved === 'dark') return saved
  } catch {
    // Storage can be unavailable (private mode); fall through to the system setting.
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

const ThemeContext = createContext<{ theme: Theme; toggleTheme: () => void } | null>(null)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(initialTheme)

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
  }, [theme])

  const toggleTheme = useCallback(() => {
    setTheme((current) => {
      const next = current === 'dark' ? 'light' : 'dark'
      try {
        localStorage.setItem(STORAGE_KEY, next)
      } catch {
        // The choice still applies for this visit.
      }
      return next
    })
  }, [])

  const value = useMemo(() => ({ theme, toggleTheme }), [theme, toggleTheme])
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  const context = useContext(ThemeContext)
  if (!context) throw new Error('useTheme must be used inside <ThemeProvider>')
  return context
}

/**
 * Colours for charts. Recharts writes colours into SVG attributes, where CSS
 * variables do not resolve, so charts take them from here instead of Tailwind.
 */
export function useChartColours() {
  const { theme } = useTheme()
  const dark = theme === 'dark'
  return {
    grid: dark ? '#35594B' : '#E3E9E5',
    axis: dark ? '#ACBBB3' : '#55625B',
    zero: dark ? '#8FA398' : '#8A968F',
    /** The portfolio's own line */
    primary: dark ? '#9DD8BD' : '#1E3A2F',
    area: dark ? '#2C5142' : '#EAF0EC',
    gold: '#C9A24B',
    loss: dark ? '#F0AA7A' : '#C2703D',
    /** The benchmark: neither gain, loss nor gold */
    benchmark: dark ? '#A9C4EA' : '#4A6FA5',
    /** Kinds of holding. None is the gain or loss colour: a kind is not a result. */
    allocation: {
      stock: dark ? '#9DD8BD' : '#1E3A2F',
      etf: dark ? '#4FA583' : '#5E9C82',
      option: dark ? '#B4C2BA' : '#B9C4BD',
      other: dark ? '#A9C4EA' : '#4A6FA5',
      cash: '#C9A24B',
      track: dark ? '#305646' : '#EAF0EC',
    },
    tooltip: {
      backgroundColor: dark ? '#11211B' : '#FFFFFF',
      border: `1px solid ${dark ? '#35594B' : '#EAF0EC'}`,
      borderRadius: 8,
      color: dark ? '#EEF3F0' : '#14201C',
    },
  }
}
