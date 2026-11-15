import type { ReactNode } from 'react'
import { ErrorState } from './ErrorState'
import { Skeleton } from './Skeleton'

interface Query {
  isLoading: boolean
  isError: boolean
  refetch: () => unknown
}

/**
 * One section's data: placeholders while it loads, an error with "Try again" if it fails,
 * else the section. So an empty table never stands in for a request that failed or is running.
 */
export function QueryState({ query, error, children }: { query: Query; error: string; children: ReactNode }) {
  if (query.isLoading) {
    return (
      <div className="space-y-3 py-2" aria-busy="true">
        <Skeleton className="h-4 w-1/3" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
      </div>
    )
  }
  if (query.isError) return <ErrorState message={error} onRetry={() => query.refetch()} />
  return <>{children}</>
}
