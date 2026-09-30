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
  it('renders the guided empty state and download actions', async () => {
    mockEmptyApi()
    render(<MemoryRouter><App /></MemoryRouter>)
    expect(await screen.findByText('Begin with a single daily CSV.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /try the sample/i })).toHaveAttribute('href', '/api/v1/downloads/sample')
    expect(screen.getByRole('link', { name: /download template/i })).toHaveAttribute('href', '/api/v1/downloads/template')
  })

  it.each([
    ['/sleep', 'Nights, in sequence.'],
    ['/recovery', 'Signals that move together.'],
    ['/activity', 'Movement leaves a trace.'],
    ['/nutrition', 'Recorded intake, with context.'],
    ['/body', 'Slow measurements, clearly drawn.'],
    ['/compare', 'Put two signals on the same dates.'],
    ['/data', 'Every import leaves a receipt.'],
  ])('navigates to %s', async (route, heading) => {
    mockEmptyApi()
    render(<MemoryRouter initialEntries={[route]}><App /></MemoryRouter>)
    expect(await screen.findByRole('heading', { name: heading })).toBeInTheDocument()
  })

  it.each([
    ['/coach', 'The Coach has a place, not a voice—yet.'],
    ['/insights', 'Insights will be evidence first.'],
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
