import { useMemo, useState } from 'react'
import { CalendarDays } from 'lucide-react'
import { useAppContext } from '../context'

function shift(dateText: string, amount: number) {
  const date = new Date(`${dateText}T12:00:00`)
  date.setDate(date.getDate() + amount)
  return date.toISOString().slice(0, 10)
}

export function DateRangeControl() {
  const { range, setRange, metrics } = useAppContext()
  const [custom, setCustom] = useState(false)
  const latest = metrics?.dateRange.end
  const earliest = metrics?.dateRange.start
  const preset = useMemo(() => {
    if (!range.end || !range.start || !latest) return '30'
    if (range.start === earliest && range.end === latest) return 'all'
    if (range.end === latest && range.start === shift(latest, -29)) return '30'
    if (range.end === latest && range.start === shift(latest, -89)) return '90'
    return 'custom'
  }, [range, latest, earliest])

  const choose = (value: string) => {
    if (!latest) return
    if (value === 'all') setRange({ start: earliest ?? latest, end: latest })
    else if (value === '30') setRange({ start: shift(latest, -29), end: latest })
    else if (value === '90') setRange({ start: shift(latest, -89), end: latest })
    setCustom(value === 'custom')
  }

  if (!latest) return null
  return (
    <div className="date-control">
      <CalendarDays aria-hidden="true" size={16} />
      <label className="sr-only" htmlFor="date-preset">Date range</label>
      <select id="date-preset" value={custom ? 'custom' : preset} onChange={(event) => choose(event.target.value)}>
        <option value="30">Latest 30 days</option>
        <option value="90">Latest 90 days</option>
        <option value="all">All data</option>
        <option value="custom">Custom</option>
      </select>
      {(custom || preset === 'custom') && (
        <div className="custom-range">
          <input aria-label="Start date" type="date" value={range.start ?? ''} min={earliest ?? undefined} max={range.end ?? latest} onChange={(event) => setRange({ ...range, start: event.target.value })} />
          <span>to</span>
          <input aria-label="End date" type="date" value={range.end ?? ''} min={range.start ?? earliest ?? undefined} max={latest} onChange={(event) => setRange({ ...range, end: event.target.value })} />
        </div>
      )}
    </div>
  )
}

