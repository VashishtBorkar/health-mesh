import { Database, Download, FileSpreadsheet, Upload } from 'lucide-react'
import { downloadUrl } from '../api'
import { useAppContext } from '../context'
import { api } from '../api'
import { useRequest } from '../hooks'
import { PageHeader } from './DashboardPages'

export function DataPage() {
  const { openImport, refreshKey } = useAppContext()
  const request = useRequest(api.imports, [refreshKey])
  return (
    <main className="page-content">
      <PageHeader eyebrow="Sources and provenance" title="Data and imports" description="Files remain local, repeated uploads are idempotent, and every current value points to its latest import." />
      <section className="data-actions reveal delay-1">
        <button className="primary-button" type="button" onClick={openImport}><Upload aria-hidden="true" />Import CSV</button>
        <a className="secondary-button" href={downloadUrl('template')} download><Download aria-hidden="true" />Empty template</a>
        <a className="secondary-button" href={downloadUrl('sample')} download><Download aria-hidden="true" />90-day sample</a>
      </section>
      <section className="import-ledger reveal delay-2">
        <div className="section-heading"><div><span className="eyebrow">Import history</span><h2>Local source register</h2></div><Database aria-hidden="true" /></div>
        {!request.data?.items.length && <div className="no-imports"><FileSpreadsheet aria-hidden="true" /><p>No files have been imported.</p></div>}
        {request.data?.items.map((item, index) => (
          <article className="import-entry" key={item.id}>
            <span className="entry-index">{String(request.data!.items.length - index).padStart(2, '0')}</span>
            <div><strong>{item.filename}</strong><span>{item.dateRange.start} — {item.dateRange.end}</span></div>
            <div><span>Rows</span><strong>{item.rowsProcessed}</strong></div>
            <div><span>Added / changed</span><strong>{item.valuesCreated} / {item.valuesUpdated}</strong></div>
            <div><span>Imported</span><strong>{new Date(item.createdAt).toLocaleString()}</strong></div>
            <code title={item.sha256}>{item.sha256.slice(0, 10)}…</code>
          </article>
        ))}
      </section>
    </main>
  )
}
