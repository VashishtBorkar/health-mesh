import {
  Activity, BrainCircuit, CircleGauge, Database, Footprints, GitCompareArrows,
  HeartPulse, LayoutDashboard, MessageCircle, Moon, Scale, Upload, Utensils, FlaskConical,
} from 'lucide-react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useAppContext } from '../context'
import { DateRangeControl } from './DateRangeControl'
import { api } from '../api'
import { useRequest } from '../hooks'

const domains = [
  { to: '/', label: 'Overview', icon: LayoutDashboard },
  { to: '/sleep', label: 'Sleep', icon: Moon },
  { to: '/recovery', label: 'Recovery', icon: HeartPulse },
  { to: '/activity', label: 'Activity', icon: Footprints },
  { to: '/nutrition', label: 'Nutrition', icon: Utensils },
  { to: '/body', label: 'Body', icon: Scale },
  { to: '/compare', label: 'Compare', icon: GitCompareArrows },
  { to: '/modeling', label: 'Modeling', icon: FlaskConical },
]

export function Layout() {
  const location = useLocation()
  const { openImport } = useAppContext()
  const health = useRequest(api.health, [])
  return (
    <div className="app-shell">
      <aside className="side-rail">
        <NavLink to="/" className="brand-mark" aria-label="HealthMesh home"><Activity aria-hidden="true" /></NavLink>
        <nav className="icon-nav" aria-label="Health domains">
          {domains.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} end={to === '/'} aria-label={label} data-label={label}><Icon aria-hidden="true" /></NavLink>)}
        </nav>
        <div className="rail-spacer" />
        <span className="vertical-brand">Personal health ledger</span>
        <nav className="icon-nav utility-nav" aria-label="HealthMesh tools">
          <NavLink to="/insights" aria-label="Insights" data-label="Insights"><CircleGauge aria-hidden="true" /></NavLink>
          <NavLink to="/coach" aria-label="Coach" data-label="Coach"><MessageCircle aria-hidden="true" /></NavLink>
          <NavLink to="/data" aria-label="Data and imports" data-label="Data"><Database aria-hidden="true" /></NavLink>
        </nav>
      </aside>
      <div className="page-shell">
        <header className="app-header">
          <div className="wordmark">HealthMesh <span>{health.data?.profile === 'personal' ? 'personal history' : 'local ledger'}</span></div>
          <div className="header-actions">
            {location.pathname !== '/modeling' && <DateRangeControl />}
            <NavLink className="coach-button" to="/coach"><BrainCircuit aria-hidden="true" />Ask HealthMesh <span>Planned</span></NavLink>
            <button className="import-button" type="button" onClick={openImport}><Upload aria-hidden="true" />Import CSV</button>
          </div>
        </header>
        <Outlet />
      </div>
    </div>
  )
}

