import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { useAppContext } from '../context'
import { useRequest } from '../hooks'
import { ChartPanel, EmptyChart, ScatterChart, TrendChart } from '../components/Charts'
import { PageHeader } from './DashboardPages'

export function ComparePage() {
  const { range, metrics, refreshKey } = useAppContext()
  const available = useMemo(() => metrics?.items.filter((metric) => metric.coverage.count > 0) ?? [], [metrics])
  const [x, setX] = useState('sleep_duration_min')
  const [y, setY] = useState('hrv_ms')

  useEffect(() => {
    if (available.length && !available.some((metric) => metric.key === x)) setX(available[0].key)
    if (available.length > 1 && !available.some((metric) => metric.key === y)) setY(available[1].key)
  }, [available, x, y])

  const request = useRequest(
    () => api.compare(x, y, range),
    [x, y, range.start, range.end, refreshKey],
  )
  const xMetric = available.find((metric) => metric.key === x)
  const yMetric = available.find((metric) => metric.key === y)

  return (
    <main className="page-content">
      <PageHeader eyebrow="Comparative folio" title="Compare metrics" description="Each time series keeps its own units; the scatterplot includes only dates where both were observed." />
      <section className="compare-controls reveal delay-1">
        <label>First metric<select value={x} onChange={(event) => setX(event.target.value)}>{available.map((metric) => <option key={metric.key} value={metric.key}>{metric.label}</option>)}</select></label>
        <span>and</span>
        <label>Second metric<select value={y} onChange={(event) => setY(event.target.value)}>{available.map((metric) => <option key={metric.key} value={metric.key}>{metric.label}</option>)}</select></label>
      </section>
      {request.error && <div className="page-error" role="alert">{request.error.message}</div>}
      <div className="compare-grid reveal delay-2">
        <ChartPanel title={xMetric?.label ?? 'First metric'} subtitle={`${request.data?.xSeries?.observedCount ?? 0} observations`} description={`${xMetric?.label ?? 'First metric'} time series`} metricKeys={[x]}>{request.data?.xSeries?.observedCount ? <TrendChart series={request.data.xSeries} /> : <EmptyChart />}</ChartPanel>
        <ChartPanel title={yMetric?.label ?? 'Second metric'} subtitle={`${request.data?.ySeries?.observedCount ?? 0} observations`} description={`${yMetric?.label ?? 'Second metric'} time series`} metricKeys={[y]}>{request.data?.ySeries?.observedCount ? <TrendChart series={request.data.ySeries} color="sage" /> : <EmptyChart />}</ChartPanel>
        <ChartPanel className="scatter-panel" title="Matched relationship" subtitle={`${request.data?.matchedCount ?? 0} paired dates`} description={`Scatterplot comparing ${xMetric?.label ?? 'first metric'} and ${yMetric?.label ?? 'second metric'}`} metricKeys={[x, y]}>
          <ScatterChart pairs={request.data?.pairs ?? []} xLabel={`${xMetric?.label ?? ''} (${xMetric?.unit ?? ''})`} yLabel={`${yMetric?.label ?? ''} (${yMetric?.unit ?? ''})`} />
          <div className="correlation-note"><span>Pearson correlation</span><strong>{request.data?.correlation === null || request.data?.correlation === undefined ? 'Unavailable' : request.data.correlation.toFixed(2)}</strong><p>Exploratory association across matched dates; it does not establish cause.</p></div>
        </ChartPanel>
      </div>
    </main>
  )
}
