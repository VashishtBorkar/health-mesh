import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'
import { api } from '../api'
import { useRequest } from '../hooks'
import { usePalette } from '../components/Charts'

const labels: Record<string, string> = {
  'ridge/combined': 'Ridge · Fitbit + nutrition',
  'ridge/history': 'Ridge · HRV history',
  'ridge/fitbit': 'Ridge · Fitbit',
  'chronos/combined': 'Chronos · pretrained',
  'chronos/calibrated': 'Chronos · personal bias correction',
  'chronos/lora': 'Chronos · LoRA fine-tuning',
  trailing_median_7: 'Previous 7-day median',
  trailing_mean_7: 'Previous 7-day mean',
  training_mean: 'Training mean', training_median: 'Training median', persistence: 'Last observation',
}

export function ModelingPage() {
  const request = useRequest(api.modeling, [])
  const palette = usePalette()
  const report = request.data
  const selectedScore = report?.testModels?.find(m => m.model === report.selectedModel)
  const baselineScore = report?.testModels?.find(m => m.model === report.baseline)
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const option: EChartsOption = report?.available ? {
    animation: !reducedMotion,
    textStyle: { fontFamily: 'IBM Plex Sans Condensed', color: palette.ink },
    tooltip: { trigger: 'axis', valueFormatter: (value) => value === null ? 'Unavailable' : `${Number(value).toFixed(2)} ms` },
    legend: { bottom: 0, textStyle: { color: palette.ink } },
    grid: { left: 55, right: 20, top: 35, bottom: 70 },
    xAxis: { type: 'category', data: report.points.map(p => p.date), axisLabel: { hideOverlap: true, color: palette.muted } },
    yAxis: { type: 'value', scale: true, name: 'HRV (ms)', axisLabel: { color: palette.muted }, splitLine: { lineStyle: { color: palette.rule } } },
    aria: { enabled: true },
    series: [
      { name: 'Recorded three-day average', type: 'line', data: report.points.map(p => p.actual), connectNulls: true, symbol: 'circle', symbolSize: 6, itemStyle: { color: palette.ink } },
      { name: labels[report.selectedModel] ?? report.selectedModel, type: 'line', data: report.points.map(p => p.selected), showSymbol: false, itemStyle: { color: palette.oxblood } },
      ...(report.baseline === report.selectedModel ? [] : [{ name: labels[report.baseline] ?? report.baseline, type: 'line' as const, data: report.points.map(p => p.baseline), showSymbol: false, lineStyle: { type: 'dashed' as const }, itemStyle: { color: palette.sage } }]),
    ],
  } : {}

  return <main className="page-content modeling-page">
    <header className="page-heading reveal"><div><span className="eyebrow">Personal forecasting study</span><h1>HRV modeling</h1><p>Can your recent Fitbit and nutrition history predict average HRV over the next three days?</p></div></header>
    {request.error && <p role="alert" className="page-error">{request.error.message}</p>}
    {!report && !request.error && <p role="status">Loading experiment results…</p>}
    {report && !report.available && <section className="chart-panel"><h2>No completed experiment loaded</h2><p>Run the research experiment and its final evaluation, then start HealthMesh with the personal profile to view your results here.</p></section>}
    {report?.available && <>
      <section className="modeling-summary reveal delay-1"><div><span className="eyebrow">Selected on development data</span><h2>{labels[report.selectedModel] ?? report.selectedModel}</h2><p>Ridge is regularized linear regression. Chronos is the pretrained deep-learning model; LoRA adapts a small set of its weights to your history.</p></div><div><span className="eyebrow">Fixed experiment periods</span><p>Development: {report.developmentRange.start} – {report.developmentRange.end}<br />Final test: {report.testRange.start} – {report.testRange.end}</p><p>{report.contextDays} past calendar days per forecast. These periods are fixed and independent of the dashboard date range.</p></div></section>
      <section className="chart-panel reveal delay-2"><h2>Development comparison</h2><p>Same {report.developmentCount} scored forecast origins across three chronological folds. Lower mean absolute error (MAE) is better.</p><div className="modeling-table-wrap"><table className="modeling-table"><thead><tr><th scope="col">Model</th><th scope="col">MAE (ms)</th><th scope="col">RMSE (ms)</th></tr></thead><tbody>{[...report.developmentModels].sort((a,b) => a.mae-b.mae).map(m => <tr key={m.model}><th scope="row">{labels[m.model] ?? m.model}{m.model === report.selectedModel && <span className="eyebrow"> · Selected</span>}</th><td>{m.mae.toFixed(2)}</td><td>{m.rmse.toFixed(2)}</td></tr>)}</tbody></table></div>{report.developmentVerification && <p>{report.developmentVerification}</p>}</section>
      <section className="chart-panel"><h2>Final held-out evaluation</h2><p>The model was frozen before evaluating this period. {report.testCount} complete three-day targets were scored.</p><div className="modeling-table-wrap"><table className="modeling-table"><thead><tr><th scope="col">Model</th><th scope="col">MAE (ms)</th><th scope="col">RMSE (ms)</th></tr></thead><tbody>{report.testModels.map(m => <tr key={m.model}><th scope="row">{labels[m.model] ?? m.model}</th><td>{m.mae.toFixed(2)}</td><td>{m.rmse.toFixed(2)}</td></tr>)}</tbody></table></div>{selectedScore && baselineScore && report.selectedModel !== report.baseline && <p><strong>{selectedScore.mae < baselineScore.mae ? 'The selected model had lower error on this test.' : 'The simple baseline performed better on this test. A forecasting improvement from the learned model has not been demonstrated.'}</strong> The development selection remains recorded; it was not changed after seeing the test.</p>}</section>
      <section className="chart-panel"><h2>Recorded versus predicted HRV</h2><p>Historical test forecasts, plotted at the first of their three target dates. Missing outcomes have no recorded point.</p><div role="img" aria-label="Held-out recorded three-day average HRV compared with the selected model and baseline, in milliseconds"><ReactECharts option={option} style={{ height: 350 }} notMerge /></div></section>
      <section className="chart-panel"><h2>What this experiment establishes</h2><ul>{report.limitations.map(text => <li key={text}>{text}</li>)}</ul><p>Coach and anomaly detection remain planned. This page displays saved experiment results and does not run a model.</p></section>
    </>}
  </main>
}
