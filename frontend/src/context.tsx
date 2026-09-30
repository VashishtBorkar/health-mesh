import { createContext, useContext } from 'react'
import type { DateRange, MetricsResponse } from './types'

export type AppContextValue = {
  range: DateRange
  setRange: (range: DateRange) => void
  metrics: MetricsResponse | null
  loadingMetrics: boolean
  openImport: () => void
  refreshKey: number
}

export const AppContext = createContext<AppContextValue | null>(null)

export function useAppContext() {
  const value = useContext(AppContext)
  if (!value) throw new Error('AppContext is unavailable')
  return value
}

