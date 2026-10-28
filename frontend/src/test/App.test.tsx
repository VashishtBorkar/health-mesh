import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { ImportDialog } from '../components/ImportDialog'

const emptyMetrics = { dateRange: { start: null, end: null }, items: [] }

function response(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  }))
}

function mockEmptyApi() {
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/metrics')) return response(emptyMetrics)
    if (url.includes('/overview')) return response({ dateRange: { start: null, end: null }, hasData: false, summaries: {}, coverage: [], latestImport: null })
    if (url.includes('/timeseries')) return response({ dateRange: { start: null, end: null }, series: [] })
    if (url.includes('/imports')) return response({ items: [] })
    if (url.includes('/capabilities')) return response({ dataPlatform: true, coach: false, insights: false })
    if (url.includes('/nutrition-completeness')) return response({ complete: 0, partial: 0, unknown: 0 })
    if (url.includes('/compare')) return response({ dateRange: { start: null, end: null }, xSeries: null, ySeries: null, pairs: [], matchedCount: 0, correlation: null })
    return response({})
  }))
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  vi.unstubAllGlobals()
})

describe('Vital Ledger application', () => {
  it('shows the modeling empty state without claiming working inference', async () => {
    mockEmptyApi()
    render(<MemoryRouter initialEntries={['/modeling']}><App /></MemoryRouter>)
    expect(await screen.findByText('No completed experiment loaded')).toBeInTheDocument()
  })

  it('renders saved modeling results with fixed periods and honest model labels', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/metrics')) return response({ dateRange: { start: '2026-08-14', end: '2026-10-21' }, items: [] })
      if (url.includes('/modeling/report')) return response({
        available: true, selectedModel: 'ridge/combined', baseline: 'trailing_median_7', contextDays: 7,
        developmentRange: { start: '2026-09-17', end: '2026-10-07' }, testRange: { start: '2026-10-08', end: '2026-10-21' },
        developmentCount: 10, testCount: 6,
        developmentModels: [{ model: 'ridge/combined', mae: 9.33, rmse: 12.66 }, { model: 'chronos/lora', mae: 20.16, rmse: 26.01 }],
        testModels: [{ model: 'ridge/combined', mae: 10.1, rmse: 12.1 }, { model: 'trailing_median_7', mae: 6.4, rmse: 8.1 }],
        points: [{ date: '2026-10-08', targetEnd: '2026-10-10', actual: null, selected: 70, baseline: 75 }],
        limitations: ['Historical backtest, not a live forecast.'],
      })
      return response({})
    }))
    render(<MemoryRouter initialEntries={['/modeling']}><App /></MemoryRouter>)
    expect(await screen.findByRole('heading', { name: 'Final held-out evaluation' })).toBeInTheDocument()
    expect(screen.getByText('Chronos · LoRA fine-tuning')).toBeInTheDocument()
    expect(screen.getByText('9.33')).toBeInTheDocument()
    expect(screen.getByText(/the simple baseline performed better on this test/i)).toBeInTheDocument()
    expect(screen.getByText(/historical backtest, not a live forecast/i)).toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Date range' })).not.toBeInTheDocument()
  })

  it('renders the guided empty state and download actions', async () => {
    mockEmptyApi()
    render(<MemoryRouter><App /></MemoryRouter>)
    expect(await screen.findByText('Begin with a single daily CSV.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /try the sample/i })).toHaveAttribute('href', '/api/v1/downloads/sample')
    expect(screen.getByRole('link', { name: /download template/i })).toHaveAttribute('href', '/api/v1/downloads/template')
  })

  it('shows units alongside overview summary values', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/analytics/overview')) return response({
        dateRange: { start: '2026-03-02', end: '2026-03-31' },
        hasData: true,
        summaries: {
          sleep: { value: 438, count: 28, change: null },
          steps: { value: 8039, count: 30, change: null },
          calories: { value: 2326, count: 27, change: null },
          weight: { value: 176, count: 15, change: -4.1 },
        },
        coverage: [],
        latestImport: null,
      })
      if (url.includes('/analytics/timeseries')) return response({ dateRange: { start: '2026-03-02', end: '2026-03-31' }, series: [] })
      if (url.includes('/metrics')) return response({ dateRange: { start: '2026-01-01', end: '2026-03-31' }, items: [] })
      return response({})
    }))
    render(<MemoryRouter><App /></MemoryRouter>)
    expect(await screen.findByText('8,039 steps')).toBeInTheDocument()
    expect(screen.getByText('2,326 kcal')).toBeInTheDocument()
    expect(screen.getByText('176 lb')).toBeInTheDocument()
  })

  it.each([
    ['/sleep', 'Sleep metrics'],
    ['/recovery', 'Recovery'],
    ['/activity', 'Activity'],
    ['/nutrition', 'Nutrition'],
    ['/body', 'Body metrics'],
    ['/compare', 'Compare metrics'],
    ['/data', 'Data and imports'],
  ])('navigates to %s', async (route, heading) => {
    mockEmptyApi()
    render(<MemoryRouter initialEntries={[route]}><App /></MemoryRouter>)
    expect(await screen.findByRole('heading', { name: heading })).toBeInTheDocument()
  })

  it.each([
    ['/coach', 'HealthMesh Coach'],
    ['/insights', 'Insights'],
  ])('shows a truthful planned state at %s', async (route, heading) => {
    mockEmptyApi()
    render(<MemoryRouter initialEntries={[route]}><App /></MemoryRouter>)
    expect(await screen.findByRole('heading', { name: heading })).toBeInTheDocument()
    expect(await screen.findByText('Disabled')).toBeInTheDocument()
    expect(screen.getByText('None')).toBeInTheDocument()
  })

  it('previews and submits a CSV', async () => {
    const fetchMock = vi.fn(() => response({
      importId: 1,
      status: 'completed',
      filename: 'small.csv',
      dateRange: { start: '2026-01-01', end: '2026-01-01' },
      rowsProcessed: 1,
      valuesCreated: 1,
      valuesUpdated: 0,
      valuesUnchanged: 0,
      valuesIgnored: 0,
      warnings: [],
    }))
    vi.stubGlobal('fetch', fetchMock)
    const imported = vi.fn()
    render(<ImportDialog open onClose={() => {}} onImported={imported} />)
    const file = new File(['date,steps\n2026-01-01,1000\n'], 'small.csv', { type: 'text/csv' })
    Object.defineProperty(file, 'text', { value: async () => 'date,steps\n2026-01-01,1000\n' })
    fireEvent.change(screen.getByLabelText(/drop a healthmesh csv here/i), { target: { files: [file] } })
    expect(await screen.findByText('small.csv')).toBeInTheDocument()
    expect(screen.getByText('2026-01-01')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Import CSV' }))
    await waitFor(() => expect(imported).toHaveBeenCalledTimes(1))
    expect(await screen.findByText('Your ledger is ready.')).toBeInTheDocument()
  })
})
