import { useEffect, useRef, useState, type DragEvent } from 'react'
import Papa from 'papaparse'
import { Check, Download, FileSpreadsheet, Upload, X } from 'lucide-react'
import { api, downloadUrl } from '../api'
import type { ImportResult } from '../types'

type ImportError = {
  message?: string
  errors?: Array<{ row: number | null; column: string | null; message: string }>
  warnings?: string[]
}

const RECOGNIZED_COLUMNS = new Set([
  'date', 'sleep_duration_min', 'sleep_efficiency_pct', 'deep_sleep_min', 'rem_sleep_min',
  'light_sleep_min', 'hrv_ms', 'resting_heart_rate_bpm', 'respiratory_rate_bpm', 'steps',
  'active_calories_kcal', 'total_calories_burned_kcal', 'workout_duration_min', 'training_load',
  'calories_consumed_kcal', 'protein_g', 'carbohydrates_g', 'fat_g', 'fiber_g',
  'nutrition_complete', 'weight_lb', 'body_fat_pct',
])

export function ImportDialog({ open, onClose, onImported }: {
  open: boolean
  onClose: () => void
  onImported: (result: ImportResult) => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string[][]>([])
  const [columns, setColumns] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<ImportError | null>(null)
  const [result, setResult] = useState<ImportResult | null>(null)
  const recognized = columns.filter((column) => RECOGNIZED_COLUMNS.has(column))

  useEffect(() => {
    if (open && !dialog.current?.open) dialog.current?.showModal()
    if (!open && dialog.current?.open) dialog.current.close()
  }, [open])

  const reset = () => {
    setFile(null)
    setPreview([])
    setColumns([])
    setError(null)
    setResult(null)
    setLoading(false)
  }

  const close = () => {
    dialog.current?.close()
    reset()
    onClose()
  }

  const selectFile = async (selected: File | undefined) => {
    if (!selected) return
    setFile(selected)
    setError(null)
    setResult(null)
    const text = await selected.text()
    const parsed = Papa.parse<string[]>(text, { preview: 6, skipEmptyLines: true })
    const rows = parsed.data
    setColumns(rows[0] ?? [])
    setPreview(rows.slice(1, 6))
  }

  const drop = (event: DragEvent) => {
    event.preventDefault()
    void selectFile(event.dataTransfer.files[0])
  }

  const submit = async () => {
    if (!file) return
    setLoading(true)
    setError(null)
    try {
      const imported = await api.importCsv(file)
      setResult(imported)
      onImported(imported)
    } catch (reason) {
      const typed = reason as Error & { detail?: ImportError }
      setError(typed.detail ?? { message: typed.message })
    } finally {
      setLoading(false)
    }
  }

  return (
    <dialog ref={dialog} className="import-dialog" onCancel={(event) => { event.preventDefault(); close() }}>
      <div className="dialog-heading">
        <div><span className="eyebrow">Local data import</span><h2>Bring a CSV into your ledger</h2></div>
        <button className="icon-button" type="button" onClick={close} aria-label="Close import dialog"><X aria-hidden="true" /></button>
      </div>
      {!file && !result && (
        <>
          <label className="drop-zone" onDragOver={(event) => event.preventDefault()} onDrop={drop}>
            <Upload aria-hidden="true" />
            <strong>Drop a HealthMesh CSV here</strong>
            <span>or choose a UTF-8 file up to 10 MB</span>
            <input type="file" accept=".csv,text/csv" onChange={(event) => void selectFile(event.target.files?.[0])} />
          </label>
          <div className="download-row">
            <a href={downloadUrl('template')} download><Download aria-hidden="true" />Empty template</a>
            <a href={downloadUrl('sample')} download><Download aria-hidden="true" />90-day sample</a>
          </div>
        </>
      )}
      {file && !result && (
        <>
          <div className="file-summary"><FileSpreadsheet aria-hidden="true" /><div><strong>{file.name}</strong><span>{recognized.length} recognized fields · {columns.length} total columns · {(file.size / 1024).toFixed(1)} KB</span><span title={recognized.join(', ')}>Recognized: {recognized.join(', ') || 'none'}</span></div><button type="button" className="text-button" onClick={reset}>Choose another</button></div>
          <div className="preview-table" aria-label="First five CSV rows">
            <table><thead><tr>{columns.map((column, index) => <th key={`${column}-${index}`}>{column}</th>)}</tr></thead><tbody>{preview.map((row, rowIndex) => <tr key={rowIndex}>{columns.map((_, columnIndex) => <td key={columnIndex}>{row[columnIndex] || <span className="blank-value">blank</span>}</td>)}</tr>)}</tbody></table>
          </div>
          {error && (
            <div className="error-box" role="alert">
              <strong>{error.message ?? 'The CSV could not be imported.'}</strong>
              {error.errors?.slice(0, 8).map((issue, index) => <p key={index}>{issue.row ? `Row ${issue.row}` : 'File'}{issue.column ? ` · ${issue.column}` : ''}: {issue.message}</p>)}
            </div>
          )}
          <div className="dialog-actions"><button type="button" className="secondary-button" onClick={close}>Cancel</button><button type="button" className="primary-button" disabled={loading} onClick={() => void submit()}>{loading ? 'Validating…' : 'Import CSV'}</button></div>
        </>
      )}
      {result && (
        <div className="import-success" aria-live="polite">
          <span className="success-mark"><Check aria-hidden="true" /></span>
          <span className="eyebrow">Import complete</span>
          <h2>{result.status === 'duplicate' ? 'This file was already imported.' : 'Your ledger is ready.'}</h2>
          <p>{result.rowsProcessed} rows · {result.valuesCreated} values added · {result.valuesUpdated} updated · {result.valuesUnchanged} unchanged · {result.valuesIgnored} blank values ignored</p>
          {result.dateRange.start && result.dateRange.end && <p>Coverage: {result.dateRange.start} — {result.dateRange.end}</p>}
          {result.warnings.length > 0 && <div className="warning-box">{result.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div>}
          <button type="button" className="primary-button" onClick={close}>View dashboard</button>
        </div>
      )}
    </dialog>
  )
}
