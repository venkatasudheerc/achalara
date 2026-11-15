import { createContext, useContext, useState, useEffect, type ReactNode } from 'react'

interface DateRange { startDate: string | undefined; endDate: string | undefined }
interface DateRangeCtx extends DateRange {
  setDateRange: (start: string | undefined, end: string | undefined) => void
  clearDateRange: () => void
}

const STORAGE_KEY = 'achalara.dateRange'

function loadDateRange(): DateRange {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (raw) return JSON.parse(raw) as DateRange
  } catch { /* unreadable or blocked storage: start empty */ }
  return { startDate: undefined, endDate: undefined }
}

const DateRangeContext = createContext<DateRangeCtx | null>(null)

export function DateRangeProvider({ children }: { children: ReactNode }) {
  const [range, setRange] = useState<DateRange>(loadDateRange)

  useEffect(() => {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(range))
  }, [range])

  const setDateRange = (start: string | undefined, end: string | undefined) =>
    setRange({ startDate: start, endDate: end })

  const clearDateRange = () => setRange({ startDate: undefined, endDate: undefined })

  return (
    <DateRangeContext.Provider value={{ ...range, setDateRange, clearDateRange }}>
      {children}
    </DateRangeContext.Provider>
  )
}

export function useDateRange() {
  const ctx = useContext(DateRangeContext)
  if (!ctx) throw new Error('useDateRange must be used within DateRangeProvider')
  return ctx
}
