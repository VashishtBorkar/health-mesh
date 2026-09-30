import { useEffect, useMemo, useState, type ReactNode } from 'react'
import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'
import { Link, useLocation } from 'react-router-dom'
import { useAppContext } from '../context'
import type { MetricSeries } from '../types'

type Palette = {
  ink: string
  muted: string
  rule: string
  paper: string
  oxblood: string
  sage: string
  mustard: string
  blue: string
}

function readPalette(): Palette {
  const style = getComputedStyle(document.documentElement)
  const value = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback
  return {
    ink: value('--ink', '#1f2924'),
    muted: value('--muted', '#6d746e'),
    rule: value('--rule', '#c9c2b3'),
    paper: value('--paper', '#f2eee4'),
    oxblood: value('--oxblood', '#8d2e2c'),
    sage: value('--sage', '#607c68'),
    mustard: value('--mustard', '#c48b25'),
    blue: value('--blue', '#3f6f85'),
  }
}

export function usePalette() {
  const [palette, setPalette] = useState(readPalette)
  useEffect(() => {
    const media = matchMedia('(prefers-color-scheme: dark)')
    const update = () => setPalette(readPalette())
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  return palette
}

export function ChartPanel({ title, subtitle, description, children, className = '', metricKeys = [] }: {
  title: string
  subtitle?: string
  description: string
  children: ReactNode
  className?: string
  metricKeys?: string[]
}) {
  const location = useLocation()
  const { range } = useAppContext()
  const params = new URLSearchParams({ route: location.pathname })
  if (range.start) params.set('startDate', range.start)
  if (range.end) params.set('endDate', range.end)
  if (metricKeys.length) params.set('metricKeys', metricKeys.join(','))
  return (
    <section className={`chart-panel ${className}`.trim()}>
      <div className="panel-heading">
        <div><h2>{title}</h2>{subtitle && <span>{subtitle}</span>}</div>
        <Link className="chart-coach-link" to={`/coach?${params}`}>Ask Coach <span>Planned</span></Link>
      </div>
      <div role="img" aria-label={description}>{children}</div>
    </section>
  )
}

export function EmptyChart({ message = 'No observations in this date range.' }: { message?: string }) {
  return <div className="empty-chart"><span>—</span><p>{message}</p></div>
}

function baseOption(palette: Palette): EChartsOption {
  return {
    animationDuration: 450,
    textStyle: { fontFamily: 'IBM Plex Sans Condensed', color: palette.ink },
    tooltip: {
      trigger: 'axis',
      backgroundColor: palette.ink,
      borderWidth: 0,
      textStyle: { color: palette.paper },
    },
    grid: { left: 48, right: 22, top: 24, bottom: 42 },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      axisLine: { lineStyle: { color: palette.rule } },
      axisTick: { show: false },
      axisLabel: { color: palette.muted, hideOverlap: true },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: palette.muted },
      splitLine: { lineStyle: { color: palette.rule, opacity: 0.62 } },
    },
    aria: { enabled: true },
  }
}

export function TrendChart({ series, color = 'oxblood', showRaw = true, height = 280 }: {
  series: MetricSeries
  color?: keyof Pick<Palette, 'oxblood' | 'sage' | 'mustard' | 'blue'>
  showRaw?: boolean
  height?: number
}) {
  const palette = usePalette()
  const option = useMemo<EChartsOption>(() => ({
    ...baseOption(palette),
    xAxis: { ...(baseOption(palette).xAxis as object), data: series.points.map((point) => point.date) },
    yAxis: { ...(baseOption(palette).yAxis as object), name: series.unit, nameTextStyle: { color: palette.muted } },
    series: [
      ...(showRaw ? [{
        name: series.label,
        type: 'line' as const,
        data: series.points.map((point) => point.value),
        connectNulls: false,
        symbol: 'circle',
        symbolSize: 5,
        lineStyle: { color: palette[color], opacity: 0.36, width: 1 },
        itemStyle: { color: palette[color] },
      }] : []),
      {
        name: '7-day average',
        type: 'line' as const,
        data: series.points.map((point) => point.rollingAverage),
        connectNulls: false,
        showSymbol: false,
        lineStyle: { color: palette[color], width: 3 },
      },
    ],
  }), [series, palette, color, showRaw])
  return <ReactECharts option={option} style={{ height }} notMerge />
}

export function MultiLineChart({ series, colors = ['oxblood', 'sage', 'blue'], height = 280 }: {
  series: MetricSeries[]
  colors?: Array<keyof Pick<Palette, 'oxblood' | 'sage' | 'mustard' | 'blue'>>
  height?: number
}) {
  const palette = usePalette()
  const observed = series.some((item) => item.observedCount > 0)
  if (!observed) return <EmptyChart />
  const dates = series[0]?.points.map((point) => point.date) ?? []
  const option: EChartsOption = {
    ...baseOption(palette),
    legend: { bottom: 0, textStyle: { color: palette.muted } },
    grid: { left: 48, right: 22, top: 24, bottom: 62 },
    xAxis: { ...(baseOption(palette).xAxis as object), data: dates },
    series: series.map((item, index) => ({
      name: `${item.label} (${item.unit})`,
      type: 'line',
      data: item.points.map((point) => point.value),
      connectNulls: false,
      showSymbol: false,
      lineStyle: { color: palette[colors[index % colors.length]], width: 2.4 },
      itemStyle: { color: palette[colors[index % colors.length]] },
    })),
  }
  return <ReactECharts option={option} style={{ height }} notMerge />
}

export function BarChart({ series, stacked = false, height = 280 }: { series: MetricSeries[]; stacked?: boolean; height?: number }) {
  const palette = usePalette()
  if (!series.some((item) => item.observedCount > 0)) return <EmptyChart />
  const dates = series[0]?.points.map((point) => point.date) ?? []
  const colors = [palette.sage, palette.mustard, palette.blue, palette.oxblood]
  const option: EChartsOption = {
    ...baseOption(palette),
    legend: { bottom: 0, textStyle: { color: palette.muted } },
    grid: { left: 48, right: 22, top: 24, bottom: 62 },
    xAxis: { ...(baseOption(palette).xAxis as object), type: 'category', boundaryGap: true, data: dates },
    series: series.map((item, index) => ({
      name: `${item.label} (${item.unit})`,
      type: 'bar',
      stack: stacked ? 'total' : undefined,
      data: item.points.map((point) => point.value),
      itemStyle: { color: colors[index % colors.length], opacity: .82 },
      barMaxWidth: 20,
    })),
  }
  return <ReactECharts option={option} style={{ height }} notMerge />
}

export function ScatterChart({ pairs, xLabel, yLabel, height = 280 }: {
  pairs: Array<{ x: number; y: number }>
  xLabel: string
  yLabel: string
  height?: number
}) {
  const palette = usePalette()
  if (!pairs.length) return <EmptyChart message="No matched dates are available." />
  const option: EChartsOption = {
    ...baseOption(palette),
    tooltip: { trigger: 'item', backgroundColor: palette.ink, borderWidth: 0, textStyle: { color: palette.paper } },
    xAxis: { type: 'value', name: xLabel, nameLocation: 'middle', nameGap: 30, axisLabel: { color: palette.muted }, splitLine: { lineStyle: { color: palette.rule } } },
    yAxis: { type: 'value', name: yLabel, nameLocation: 'middle', nameGap: 38, axisLabel: { color: palette.muted }, splitLine: { lineStyle: { color: palette.rule } } },
    series: [{ type: 'scatter', data: pairs.map((pair) => [pair.x, pair.y]), symbolSize: 8, itemStyle: { color: palette.oxblood, opacity: .72 } }],
  }
  return <ReactECharts option={option} style={{ height }} notMerge />
}

export function seriesMap(items: MetricSeries[]) {
  return Object.fromEntries(items.map((item) => [item.key, item])) as Record<string, MetricSeries>
}
