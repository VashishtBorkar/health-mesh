import { useEffect, useState } from 'react'
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { api } from './api'
import { AppContext } from './context'
import type { DateRange, ImportResult, MetricsResponse } from './types'
import { ImportDialog } from './components/ImportDialog'
import { Layout } from './components/Layout'
import { ActivityPage, BodyPage, IntelligenceSkeleton, NutritionPage, OverviewPage, RecoveryPage, SleepPage } from './pages/DashboardPages'
import { ComparePage } from './pages/ComparePage'
import { DataPage } from './pages/DataPage'
import { ModelingPage } from './pages/ModelingPage'

function shift(dateText: string, amount: number) {
  const date = new Date(`${dateText}T12:00:00`)
  date.setDate(date.getDate() + amount)
  return date.toISOString().slice(0, 10)
}

export default function App() {
  const navigate = useNavigate()
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null)
  const [loadingMetrics, setLoadingMetrics] = useState(true)
  const [range, setRange] = useState<DateRange>({ start: null, end: null })
  const [importOpen, setImportOpen] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)

  useEffect(() => {
    let active = true
    setLoadingMetrics(true)
    api.metrics().then((response) => {
      if (!active) return
      setMetrics(response)
      if (response.dateRange.end && (!range.start || !range.end)) {
        setRange({ start: shift(response.dateRange.end, -29), end: response.dateRange.end })
      }
    }).finally(() => active && setLoadingMetrics(false))
    return () => { active = false }
    // Refresh is intentionally the only reload trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey])

  const imported = (result: ImportResult) => {
    setRefreshKey((value) => value + 1)
    if (result.dateRange.start && result.dateRange.end) setRange(result.dateRange)
    navigate('/')
  }

  return (
    <AppContext.Provider value={{ range, setRange, metrics, loadingMetrics, openImport: () => setImportOpen(true), refreshKey }}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<OverviewPage />} />
          <Route path="sleep" element={<SleepPage />} />
          <Route path="recovery" element={<RecoveryPage />} />
          <Route path="activity" element={<ActivityPage />} />
          <Route path="nutrition" element={<NutritionPage />} />
          <Route path="body" element={<BodyPage />} />
          <Route path="compare" element={<ComparePage />} />
          <Route path="data" element={<DataPage />} />
          <Route path="modeling" element={<ModelingPage />} />
          <Route path="insights" element={<IntelligenceSkeleton type="insights" />} />
          <Route path="coach" element={<IntelligenceSkeleton type="coach" />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
      <ImportDialog open={importOpen} onClose={() => setImportOpen(false)} onImported={imported} />
    </AppContext.Provider>
  )
}

