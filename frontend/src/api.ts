import type { CompareResponse, DateRange, ImportItem, ImportResult, MetricsResponse, OverviewResponse, TimeseriesResponse } from './types'

const API = '/api/v1'

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: { message: response.statusText } }))
    const error = new Error(body.detail?.message ?? 'Request failed') as Error & { detail?: unknown }
    error.detail = body.detail
    throw error
  }
  return response.json() as Promise<T>
}

function rangeQuery(range: DateRange) {
  const params = new URLSearchParams()
  if (range.start) params.set('start', range.start)
  if (range.end) params.set('end', range.end)
  return params
}

export const api = {
  metrics: () => fetch(`${API}/metrics`).then((response) => parseResponse<MetricsResponse>(response)),
  overview: (range: DateRange) => {
    const params = rangeQuery(range)
    return fetch(`${API}/analytics/overview?${params}`).then((response) => parseResponse<OverviewResponse>(response))
  },
  timeseries: (keys: string[], range: DateRange) => {
    const params = rangeQuery(range)
    params.set('metrics', keys.join(','))
    params.set('rolling', '7')
    return fetch(`${API}/analytics/timeseries?${params}`).then((response) => parseResponse<TimeseriesResponse>(response))
  },
  compare: (x: string, y: string, range: DateRange) => {
    const params = rangeQuery(range)
    params.set('x', x)
    params.set('y', y)
    return fetch(`${API}/analytics/compare?${params}`).then((response) => parseResponse<CompareResponse>(response))
  },
  completeness: (range: DateRange) => {
    const params = rangeQuery(range)
    return fetch(`${API}/analytics/nutrition-completeness?${params}`).then((response) => parseResponse<Record<string, number>>(response))
  },
  imports: () => fetch(`${API}/imports`).then((response) => parseResponse<{ items: ImportItem[] }>(response)),
  importCsv: async (file: File) => {
    const body = new FormData()
    body.append('file', file)
    return fetch(`${API}/imports/csv`, { method: 'POST', body }).then((response) => parseResponse<ImportResult>(response))
  },
  capabilities: () => fetch(`${API}/capabilities`).then((response) => parseResponse<Record<string, boolean>>(response)),
}

export function downloadUrl(kind: 'template' | 'sample') {
  return `${API}/downloads/${kind}`
}

