import { useEffect, useState } from 'react'
import { api } from './api'
import { useAppContext } from './context'
import type { TimeseriesResponse } from './types'

export function useRequest<T>(loader: () => Promise<T>, dependencies: unknown[]) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    loader()
      .then((result) => active && setData(result))
      .catch((reason) => active && setError(reason instanceof Error ? reason : new Error(String(reason))))
      .finally(() => active && setLoading(false))
    return () => { active = false }
    // The caller supplies a stable, explicit dependency list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, dependencies)

  return { data, loading, error }
}

export function useTimeseries(keys: string[]): { data: TimeseriesResponse | null; loading: boolean; error: Error | null } {
  const { range, refreshKey } = useAppContext()
  const key = keys.join(',')
  return useRequest(() => api.timeseries(keys, range), [key, range.start, range.end, refreshKey])
}

