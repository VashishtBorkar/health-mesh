export type DateRange = { start: string | null; end: string | null }

export type MetricDefinition = {
  key: string
  domain: string
  label: string
  unit: string
  aggregation: string
  display: { chartType: string; precision: number }
  coverage: { count: number; start: string | null; end: string | null }
}

export type MetricsResponse = {
  dateRange: DateRange
  items: MetricDefinition[]
}

export type SeriesPoint = {
  date: string
  value: number | null
  rollingAverage: number | null
}

export type MetricSeries = {
  key: string
  label: string
  unit: string
  domain: string
  observedCount: number
  coverage: number
  points: SeriesPoint[]
}

export type TimeseriesResponse = {
  dateRange: DateRange
  series: MetricSeries[]
}

export type SummaryValue = { value: number | null; count: number; change: number | null }

export type OverviewResponse = {
  dateRange: DateRange
  hasData: boolean
  summaries: Record<'sleep' | 'steps' | 'calories' | 'weight', SummaryValue>
  coverage: Array<{ key: string; label: string; count: number; days: number; ratio: number }>
  latestImport: { id: number; filename: string; createdAt: string } | null
}

export type ImportResult = {
  importId: number
  status: string
  filename: string
  dateRange: DateRange
  rowsProcessed: number
  valuesCreated: number
  valuesUpdated: number
  valuesUnchanged: number
  valuesIgnored: number
  warnings: string[]
}

export type ImportItem = ImportResult & {
  id: number
  sha256: string
  columns: string[]
  createdAt: string
}

export type CompareResponse = {
  dateRange: DateRange
  xSeries: MetricSeries | null
  ySeries: MetricSeries | null
  pairs: Array<{ date: string; x: number; y: number }>
  matchedCount: number
  correlation: number | null
}

