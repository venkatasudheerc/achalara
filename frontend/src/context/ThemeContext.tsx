import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

export type Theme = 'light' | 'dark'
/** What a viewer chooses: a theme, or whatever their device uses */
export type ThemeChoice = Theme | 'system'

/** Where the viewer's choice is kept; index.html reads it before first paint. */
const STORAGE_KEY = 'achalara-theme'

/**
 * Whether viewers of the older screens (the advisor workspace and the old
 * portal) may choose light or dark. While false those screens are dark for
 * everyone. The new app (`/home`) and the sign-in pages always honour the
 * viewer's choice; they mark themselves with useOneAppLook().
 */
export const THEME_CHOICE_OFFERED = false

function savedChoice(): ThemeChoice {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'light' || saved === 'dark' || saved === 'system') return saved
  } catch {
    // Storage can be unavailable (private mode); fall through to the device's setting.
  }
  return 'system'
}

const prefersDark = () => !!window.matchMedia?.('(prefers-color-scheme: dark)').matches

interface ThemeState {
  /** The theme in effect */
  theme: Theme
  choice: ThemeChoice
  setChoice: (choice: ThemeChoice) => void
  toggleTheme: () => void
  /** True on the new app's pages, which have their own look */
  oneApp: boolean
  setOneApp: (on: boolean) => void
}

const ThemeContext = createContext<ThemeState | null>(null)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoiceState] = useState<ThemeChoice>(savedChoice)
  const [systemDark, setSystemDark] = useState(prefersDark)
  const [oneApp, setOneApp] = useState(() => document.documentElement.classList.contains('one-app'))

  // Follow the device while the choice is "system".
  useEffect(() => {
    const query = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!query) return
    const onChange = () => setSystemDark(query.matches)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  const chosen: Theme = choice === 'system' ? (systemDark ? 'dark' : 'light') : choice
  const theme: Theme = oneApp || THEME_CHOICE_OFFERED ? chosen : 'dark'

  useEffect(() => {
    const root = document.documentElement
    root.classList.toggle('dark', theme === 'dark')
    root.classList.toggle('one-app', oneApp)
  }, [theme, oneApp])

  const setChoice = useCallback((next: ThemeChoice) => {
    setChoiceState(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // The choice still applies for this visit.
    }
  }, [])

  const toggleTheme = useCallback(() => setChoice(theme === 'dark' ? 'light' : 'dark'), [theme, setChoice])

  const value = useMemo(
    () => ({ theme, choice, setChoice, toggleTheme, oneApp, setOneApp }),
    [theme, choice, setChoice, toggleTheme, oneApp],
  )
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  const context = useContext(ThemeContext)
  if (!context) throw new Error('useTheme must be used inside <ThemeProvider>')
  return context
}

/** Marks the page as part of the new app while it is shown: its look and the viewer's theme. */
export function useOneAppLook() {
  const { setOneApp } = useTheme()
  useEffect(() => {
    setOneApp(true)
    return () => setOneApp(false)
  }, [setOneApp])
}

/**
 * Colours for charts. Recharts writes colours into SVG attributes, where CSS
 * variables do not resolve, so charts take them from here instead of Tailwind.
 */
export function useChartColours() {
  const { theme, oneApp } = useTheme()
  const dark = theme === 'dark'
  if (oneApp) return oneAppChartColours(dark)
  return {
    grid: dark ? '#35594B' : '#E3E9E5',
    axis: dark ? '#ACBBB3' : '#55625B',
    zero: dark ? '#8FA398' : '#8A968F',
    /** The portfolio's own line */
    primary: dark ? '#9DD8BD' : '#1E3A2F',
    area: dark ? '#2C5142' : '#EAF0EC',
    gold: '#C9A24B',
    loss: dark ? '#F0AA7A' : '#C2703D',
    /** A diverging scale for heatmaps: a loss end, a neutral grey middle, a gain end.
     *  Ends are deep enough that ink text on them stays readable. */
    diverging: dark
      ? { loss: '#A8572B', mid: '#3B4A44', gain: '#25775B', text: '#EEF3F0' }
      : { loss: '#C2703D', mid: '#EEF1EF', gain: '#2E8B6B', text: '#14201C' },
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

/** The new app's chart colours: violet for the portfolio, green and clay for results. */
function oneAppChartColours(dark: boolean) {
  return {
    grid: dark ? '#2C2A3A' : '#ECEBF2',
    axis: dark ? '#A9A7BC' : '#5A5870',
    zero: dark ? '#45425A' : '#D6D4E2',
    primary: dark ? '#A8A0FF' : '#4B3FD6',
    area: dark ? '#2A2750' : '#ECE9FB',
    gold: dark ? '#A8A0FF' : '#4B3FD6',
    loss: dark ? '#F0996A' : '#B4531F',
    diverging: dark
      ? { loss: '#9C4F25', mid: '#2A2838', gain: '#1F7A55', text: '#F1F0F7' }
      : { loss: '#EC9662', mid: '#F1F0F6', gain: '#62BE8E', text: '#1B1A26' },
    benchmark: dark ? '#8FB4FF' : '#1D4FBF',
    allocation: {
      stock: dark ? '#A8A0FF' : '#4B3FD6',
      etf: dark ? '#6FD6A0' : '#0F6A40',
      option: dark ? '#A9A7BC' : '#B7B5C9',
      other: dark ? '#8FB4FF' : '#1D4FBF',
      cash: dark ? '#F2BE6B' : '#8A4F00',
      track: dark ? '#2C2A3A' : '#ECEBF2',
    },
    tooltip: {
      backgroundColor: dark ? '#1A1925' : '#FFFFFF',
      border: `1px solid ${dark ? '#45425A' : '#D6D4E2'}`,
      borderRadius: 12,
      color: dark ? '#F1F0F7' : '#1B1A26',
    },
  }
}
