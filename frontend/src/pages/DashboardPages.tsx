import { useEffect, useMemo, useState } from 'react'
import { ArrowRight, Database, Download, FileSpreadsheet, Sparkles, Upload } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api, downloadUrl } from '../api'
import { useAppContext } from '../context'
import { useRequest, useTimeseries } from '../hooks'
import type { MetricSeries, SeriesPoint } from '../types'
import { BarChart, ChartPanel, EmptyChart, MultiLineChart, ScatterChart, seriesMap, TrendChart } from '../components/Charts'

export function PageHeader({ eyebrow, title, description }: { eyebrow: string; title: string; description: string }) {
  const { range } = useAppContext()
  return (
    <header className="page-heading reveal">
      <div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>
      {range.start && range.end && <div className="period-stamp"><span>Reporting period</span><strong>{formatDate(range.start)} — {formatDate(range.end)}</strong></div>}
    </header>
  )
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' }).format(new Date(`${value}T12:00:00`))
}

function formatNumber(value: number | null, digits = 0) {
  if (value === null) return '—'
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: digits }).format(value)
}

function formatDuration(value: number | null) {
  if (value === null) return '—'
  const hours = Math.floor(value / 60)
  return `${hours}h ${Math.round(value % 60)}m`
}

function LoadingPage() {
  return <div className="loading-page" aria-live="polite"><span /><p>Reading your ledger…</p></div>
}

function ErrorPage({ error }: { error: Error }) {
  return <div className="page-error" role="alert"><strong>HealthMesh could not load this view.</strong><p>{error.message}</p></div>
}

function EmptyState() {
  const { openImport } = useAppContext()
  return (
    <section className="empty-ledger reveal">
      <div className="folio-number">00</div>
      <span className="eyebrow">Your private health ledger</span>
      <h1>Begin with a single daily CSV.</h1>
      <p>Import the HealthMesh template to turn sleep, recovery, movement, nutrition, and body measurements into one connected record.</p>
      <div className="empty-actions"><button className="primary-button" type="button" onClick={openImport}><Upload aria-hidden="true" />Import your CSV</button><a className="secondary-button" href={downloadUrl('sample')} download><Download aria-hidden="true" />Try the sample</a></div>
      <ol className="empty-steps"><li><span>01</span><strong>Prepare</strong><p>Use the documented daily template. Only date and one metric are required.</p></li><li><span>02</span><strong>Import</strong><p>HealthMesh validates every row before changing your local database.</p></li><li><span>03</span><strong>Explore</strong><p>Move through focused domain pages and compare aligned metrics.</p></li></ol>
      <div className="template-note"><FileSpreadsheet aria-hidden="true" /><div><strong>Need the field definitions?</strong><span>Download the empty template and read its data dictionary.</span></div><a href={downloadUrl('template')} download>Download template <ArrowRight aria-hidden="true" /></a></div>
    </section>
  )
}

function Stat({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="ledger-stat"><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>
}

function findSeries(series: MetricSeries[], key: string) {
  return series.find((item) => item.key === key)
}

function derivedSeries(a: MetricSeries | undefined, b: MetricSeries | undefined, key: string, label: string, unit: string, subtract = false): MetricSeries | undefined {
  if (!a || !b) return undefined
  const points: SeriesPoint[] = a.points.map((point, index) => {
    const other = b.points[index]
    const value = point.value !== null && other?.value !== null ? (subtract ? point.value - other.value : point.value + other.value) : null
    return { date: point.date, value, rollingAverage: null }
  })
  const observed = points.filter((point) => point.value !== null).length
  return { key, label, unit, domain: 'derived', observedCount: observed, coverage: points.length ? observed / points.length : 0, points }
}

export function OverviewPage() {
  const { range, refreshKey } = useAppContext()
  const overview = useRequest(() => api.overview(range), [range.start, range.end, refreshKey])
  const time = useTimeseries(['weight_lb', 'calories_consumed_kcal', 'total_calories_burned_kcal', 'sleep_duration_min', 'hrv_ms'])
  if (overview.loading || time.loading) return <LoadingPage />
  if (overview.error) return <ErrorPage error={overview.error} />
  if (!overview.data?.hasData) return <main className="page-content"><EmptyState /></main>
  const summaries = overview.data.summaries
  const map = seriesMap(time.data?.series ?? [])
  const balance = derivedSeries(map.calories_consumed_kcal, map.total_calories_burned_kcal, 'energy_balance', 'Energy balance', 'kcal', true)
  return (
    <main className="page-content">
      <PageHeader eyebrow="Monthly folio · Overview" title="The shape of your month." description="A connected view of the measurements you chose to record." />
      <section className="ledger-stats reveal delay-1" aria-label="Summary metrics">
        <Stat label="Sleep average" value={formatDuration(summaries.sleep.value)} detail={`${summaries.sleep.count} recorded nights`} />
        <Stat label="Daily movement" value={formatNumber(summaries.steps.value)} detail={`${summaries.steps.count} recorded days`} />
        <Stat label="Energy logged" value={`${formatNumber(summaries.calories.value)} kcal`} detail={`${summaries.calories.count} recorded days`} />
        <Stat label="Weight trend" value={`${formatNumber(summaries.weight.value, 1)} lb`} detail={summaries.weight.change === null ? `${summaries.weight.count} observations` : `${summaries.weight.change > 0 ? '+' : ''}${formatNumber(summaries.weight.change, 1)} lb in period`} />
      </section>
      <div className="overview-grid reveal delay-2">
        <div className="chart-stack">
          <ChartPanel title="Weight follows the energy ledger" subtitle="Raw values and seven-day trace" description="Body-weight trend for the selected period." metricKeys={['weight_lb']}>
            {map.weight_lb?.observedCount ? <TrendChart series={map.weight_lb} /> : <EmptyChart />}
          </ChartPanel>
          <ChartPanel title="Daily energy balance" subtitle="Recorded intake minus total expenditure" description="Energy balance for dates with both intake and expenditure." metricKeys={['calories_consumed_kcal', 'total_calories_burned_kcal']}>
            {balance?.observedCount ? <BarChart series={[balance]} height={220} /> : <EmptyChart />}
          </ChartPanel>
          <ChartPanel title="Sleep and recovery" subtitle="Separate scales, aligned dates" description="Sleep duration and HRV aligned by date." metricKeys={['sleep_duration_min', 'hrv_ms']}>
            <div className="paired-plots">{map.sleep_duration_min?.observedCount ? <TrendChart series={map.sleep_duration_min} color="blue" height={200} /> : <EmptyChart />}{map.hrv_ms?.observedCount ? <TrendChart series={map.hrv_ms} color="sage" height={200} /> : <EmptyChart />}</div>
          </ChartPanel>
        </div>
        <aside className="ledger-margin">
          <div className="margin-note"><span className="folio-number">AI</span><h2>Insights are reserved</h2><p>Future anomaly detection will place explainable findings here. This phase displays no generated claims.</p><Link to="/insights">See the planned interface <ArrowRight aria-hidden="true" /></Link></div>
          <div className="margin-note"><span className="folio-number">{Math.round((overview.data.coverage.reduce((sum, item) => sum + item.ratio, 0) / Math.max(overview.data.coverage.length, 1)) * 100)}%</span><h2>Data coverage</h2><p>{overview.data.coverage.length} metrics contributed to this reporting period.</p><Link to="/data">Inspect imports <ArrowRight aria-hidden="true" /></Link></div>
          <div className="margin-note"><span className="folio-number">LLM</span><h2>Coach space is ready</h2><p>The future coach will receive the active route, metrics, and reporting period.</p><Link to="/coach">Preview Coach <ArrowRight aria-hidden="true" /></Link></div>
          {overview.data.latestImport && <div className="source-note"><Database aria-hidden="true" /><div><span>Latest source</span><strong>{overview.data.latestImport.filename}</strong></div></div>}
        </aside>
      </div>
    </main>
  )
}

export function SleepPage() {
  const request = useTimeseries(['sleep_duration_min', 'sleep_efficiency_pct', 'deep_sleep_min', 'rem_sleep_min', 'light_sleep_min'])
  if (request.loading) return <LoadingPage />
  if (request.error) return <ErrorPage error={request.error} />
  const map = seriesMap(request.data?.series ?? [])
  const duration = map.sleep_duration_min
  const efficiency = map.sleep_efficiency_pct
  return <main className="page-content"><PageHeader eyebrow="Folio 01 · Sleep" title="Nights, in sequence." description="Duration, stage composition, and efficiency without filling in missing nights." /><section className="ledger-stats compact reveal delay-1"><Stat label="Average duration" value={duration ? formatDuration(average(duration)) : '—'} detail={`${duration?.observedCount ?? 0} recorded nights`} /><Stat label="Average efficiency" value={efficiency ? `${formatNumber(average(efficiency), 1)}%` : '—'} detail={`${efficiency?.observedCount ?? 0} observations`} /></section><div className="domain-grid reveal delay-2"><ChartPanel title="Sleep duration" subtitle="Raw nights and seven-day average" description="Daily sleep duration with gaps for missing nights." metricKeys={['sleep_duration_min']}>{duration?.observedCount ? <TrendChart series={duration} color="blue" /> : <EmptyChart />}</ChartPanel><ChartPanel title="Sleep-stage composition" subtitle="Deep, REM, and light sleep" description="Stacked sleep stages by night" metricKeys={['deep_sleep_min', 'rem_sleep_min', 'light_sleep_min']}><BarChart series={[map.deep_sleep_min, map.rem_sleep_min, map.light_sleep_min].filter(Boolean)} stacked /></ChartPanel><ChartPanel title="Sleep efficiency" subtitle="Observed values" description="Sleep efficiency trend" metricKeys={['sleep_efficiency_pct']}>{efficiency?.observedCount ? <TrendChart series={efficiency} color="sage" /> : <EmptyChart />}</ChartPanel></div></main>
}

export function RecoveryPage() {
  const request = useTimeseries(['hrv_ms', 'resting_heart_rate_bpm', 'respiratory_rate_bpm', 'sleep_duration_min'])
  if (request.loading) return <LoadingPage />
  if (request.error) return <ErrorPage error={request.error} />
  const map = seriesMap(request.data?.series ?? [])
  const pairs = pairedValues(map.sleep_duration_min, map.hrv_ms)
  return <main className="page-content"><PageHeader eyebrow="Folio 02 · Recovery" title="Signals that move together." description="Personal cardiovascular and respiratory measurements shown on honest, separate scales." /><div className="domain-grid reveal delay-1"><ChartPanel title="Heart-rate variability" subtitle="Seven-day trace" description="Daily HRV trend" metricKeys={['hrv_ms']}>{map.hrv_ms?.observedCount ? <TrendChart series={map.hrv_ms} color="sage" /> : <EmptyChart />}</ChartPanel><ChartPanel title="Resting heart rate" subtitle="Seven-day trace" description="Daily resting heart-rate trend" metricKeys={['resting_heart_rate_bpm']}>{map.resting_heart_rate_bpm?.observedCount ? <TrendChart series={map.resting_heart_rate_bpm} /> : <EmptyChart />}</ChartPanel><ChartPanel title="Respiratory rate" subtitle="Recorded days" description="Daily respiratory-rate trend" metricKeys={['respiratory_rate_bpm']}>{map.respiratory_rate_bpm?.observedCount ? <TrendChart series={map.respiratory_rate_bpm} color="blue" /> : <EmptyChart />}</ChartPanel><ChartPanel title="Sleep versus HRV" subtitle={`${pairs.length} matched days · exploratory`} description="Scatterplot of sleep duration and HRV" metricKeys={['sleep_duration_min', 'hrv_ms']}><ScatterChart pairs={pairs} xLabel="Sleep (min)" yLabel="HRV (ms)" /></ChartPanel></div></main>
}

export function ActivityPage() {
  const request = useTimeseries(['steps', 'active_calories_kcal', 'workout_duration_min', 'training_load'])
  if (request.loading) return <LoadingPage />
  if (request.error) return <ErrorPage error={request.error} />
  const map = seriesMap(request.data?.series ?? [])
  const workoutDays = map.workout_duration_min?.points.filter((point) => (point.value ?? 0) > 0).length ?? 0
  return <main className="page-content"><PageHeader eyebrow="Folio 03 · Activity" title="Movement leaves a trace." description="Daily movement and deliberate training, kept distinct." /><section className="ledger-stats compact reveal delay-1"><Stat label="Average steps" value={map.steps ? formatNumber(average(map.steps)) : '—'} detail={`${map.steps?.observedCount ?? 0} recorded days`} /><Stat label="Workout days" value={String(workoutDays)} detail="Days with duration above zero" /></section><div className="domain-grid reveal delay-2"><ChartPanel title="Daily steps" subtitle="Raw count and seven-day average" description="Daily steps trend" metricKeys={['steps']}>{map.steps?.observedCount ? <TrendChart series={map.steps} color="sage" /> : <EmptyChart />}</ChartPanel><ChartPanel title="Activity energy" subtitle="Active calories" description="Daily active-calorie bars" metricKeys={['active_calories_kcal']}><BarChart series={[map.active_calories_kcal].filter(Boolean)} /></ChartPanel><ChartPanel title="Training volume" subtitle="Duration and source-defined load" description="Workout duration and training load" metricKeys={['workout_duration_min', 'training_load']}><BarChart series={[map.workout_duration_min, map.training_load].filter(Boolean)} /></ChartPanel></div></main>
}

export function NutritionPage() {
  const { range, refreshKey } = useAppContext()
  const request = useTimeseries(['calories_consumed_kcal', 'total_calories_burned_kcal', 'protein_g', 'carbohydrates_g', 'fat_g', 'fiber_g'])
  const completeness = useRequest(() => api.completeness(range), [range.start, range.end, refreshKey])
  if (request.loading || completeness.loading) return <LoadingPage />
  if (request.error) return <ErrorPage error={request.error} />
  const map = seriesMap(request.data?.series ?? [])
  const nutrition = completeness.data ?? { complete: 0, partial: 0, unknown: 0 }
  return <main className="page-content"><PageHeader eyebrow="Folio 04 · Nutrition" title="Recorded intake, with context." description="Nutrition is described as recorded intake unless you marked the day complete." /><section className="ledger-stats reveal delay-1"><Stat label="Average recorded intake" value={`${formatNumber(average(map.calories_consumed_kcal))} kcal`} detail={`${map.calories_consumed_kcal?.observedCount ?? 0} recorded days`} /><Stat label="Complete days" value={String(nutrition.complete)} detail="Explicitly marked complete" /><Stat label="Partial days" value={String(nutrition.partial)} detail="Explicitly marked partial" /><Stat label="Unknown days" value={String(nutrition.unknown)} detail="Completeness not supplied" /></section><div className="domain-grid reveal delay-2"><ChartPanel title="Intake and expenditure" subtitle="Dates remain aligned" description="Recorded calories consumed and total calories burned" metricKeys={['calories_consumed_kcal', 'total_calories_burned_kcal']}><MultiLineChart series={[map.calories_consumed_kcal, map.total_calories_burned_kcal].filter(Boolean)} /></ChartPanel><ChartPanel title="Macronutrient composition" subtitle="Grams recorded per day" description="Stacked protein, carbohydrate, and fat totals" metricKeys={['protein_g', 'carbohydrates_g', 'fat_g']}><BarChart series={[map.protein_g, map.carbohydrates_g, map.fat_g].filter(Boolean)} stacked /></ChartPanel><ChartPanel title="Protein and fiber" subtitle="Seven-day traces" description="Protein and fiber trends" metricKeys={['protein_g', 'fiber_g']}><MultiLineChart series={[map.protein_g, map.fiber_g].filter(Boolean)} /></ChartPanel></div></main>
}

export function BodyPage() {
  const request = useTimeseries(['weight_lb', 'body_fat_pct'])
  if (request.loading) return <LoadingPage />
  if (request.error) return <ErrorPage error={request.error} />
  const map = seriesMap(request.data?.series ?? [])
  const weight = map.weight_lb
  const observed = weight?.points.filter((point) => point.value !== null) ?? []
  const change = observed.length > 1 ? (observed.at(-1)!.value! - observed[0].value!) : null
  return <main className="page-content"><PageHeader eyebrow="Folio 05 · Body" title="Slow measurements, clearly drawn." description="Raw observations remain visible beneath the moving trend." /><section className="ledger-stats compact reveal delay-1"><Stat label="Latest weight" value={observed.length ? `${formatNumber(observed.at(-1)!.value, 1)} lb` : '—'} detail={`${weight?.observedCount ?? 0} observations`} /><Stat label="Period change" value={change === null ? '—' : `${change > 0 ? '+' : ''}${formatNumber(change, 1)} lb`} detail="Latest minus first observation" /></section><div className="domain-grid reveal delay-2"><ChartPanel title="Body weight" subtitle="Raw observations and seven-day average" description="Body weight trend" metricKeys={['weight_lb']}>{weight?.observedCount ? <TrendChart series={weight} /> : <EmptyChart />}</ChartPanel><ChartPanel title="Body-fat percentage" subtitle="Only recorded dates" description="Body-fat percentage trend" metricKeys={['body_fat_pct']}>{map.body_fat_pct?.observedCount ? <TrendChart series={map.body_fat_pct} color="mustard" /> : <EmptyChart />}</ChartPanel></div></main>
}

function average(series: MetricSeries | undefined) {
  if (!series) return null
  const values = series.points.flatMap((point) => point.value === null ? [] : [point.value])
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null
}

function pairedValues(x: MetricSeries | undefined, y: MetricSeries | undefined) {
  if (!x || !y) return []
  return x.points.flatMap((point, index) => point.value !== null && y.points[index]?.value !== null ? [{ x: point.value, y: y.points[index].value! }] : [])
}

export function IntelligenceSkeleton({ type }: { type: 'coach' | 'insights' }) {
  const isCoach = type === 'coach'
  const { refreshKey } = useAppContext()
  const capabilities = useRequest(api.capabilities, [refreshKey])
  const intelligenceEnabled = Boolean(capabilities.data?.[type])
  return <main className="page-content"><PageHeader eyebrow="Reserved intelligence layer" title={isCoach ? 'The Coach has a place, not a voice—yet.' : 'Insights will be evidence first.'} description={isCoach ? 'This route will become the local, tool-using interface to your health history.' : 'This route will hold personalized deviations with expected ranges and contributing measurements.'} /><section className="planned-page reveal delay-1"><span className="planned-icon"><Sparkles aria-hidden="true" /></span><span className="eyebrow">Planned for a later phase</span><h2>{isCoach ? 'Context contract ready' : 'Insight contract ready'}</h2><p>{isCoach ? 'Chart links already carry the active route, date range, and metric keys so the future local model can ask the same analytics layer for evidence.' : 'The navigation and response type are established, but no anomalies are calculated or implied in this release.'}</p><dl><div><dt>Data platform</dt><dd>{capabilities.loading ? 'Checking…' : capabilities.data?.dataPlatform ? 'Available' : 'Unavailable'}</dd></div><div><dt>{isCoach ? 'Local LLM' : 'Anomaly model'}</dt><dd>{intelligenceEnabled ? 'Available' : 'Disabled'}</dd></div><div><dt>Generated claims</dt><dd>None</dd></div></dl></section></main>
}
