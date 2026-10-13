import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ScopeProvider } from '@/context/ScopeContext'
import { DateRangeProvider } from '@/context/DateRangeContext'
import { ThemeProvider } from '@/context/ThemeContext'
import { AppRoutes } from './routes'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <BrowserRouter>
          <ScopeProvider>
            <DateRangeProvider>
              <AppRoutes />
            </DateRangeProvider>
          </ScopeProvider>
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  </React.StrictMode>
)
