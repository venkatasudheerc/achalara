import { useQuery } from '@tanstack/react-query'
import { performanceApi, type PerformanceTarget } from '@/api/endpoints/performance'
import type { PeriodGrain } from '@/api/types'

export function usePerformancePeriods(
  target: PerformanceTarget | null,
  grain: PeriodGrain,
  benchmark?: string,
) {
  const id = target
    ? target.sleeveId ?? target.accountId ?? target.clientId ?? target.strategyId
    : null
  return useQuery({
    queryKey: ['performance-periods', target?.level, id, grain, benchmark],
    queryFn: () => performanceApi.getPeriods(target!, { grain, benchmark }),
    enabled: !!target && !!id,
  })
}
