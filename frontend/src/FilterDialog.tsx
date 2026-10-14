import { useEffect, useRef, useState } from 'react'
import type { Filters } from './filters'
import { emptyFilters, validateFilters } from './filters'

const areas: Record<string, [number, number, number, number]> = {
  'Europe': [-25, 34, 45, 72],
  'Asia': [25, -10, 180, 80],
  'Africa': [-20, -35, 55, 38],
  'North America': [-170, 5, -50, 85],
  'South America': [-85, -60, -30, 15],
  'Oceania': [110, -50, -170, 5],
  'Indonesia': [94, -12, 142, 7],
}

export default function FilterDialog({ filters, onApply, onClose }: {
  filters: Filters, onApply: (filters: Filters) => void, onClose: () => void,
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [draft, setDraft] = useState(filters)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    const element = dialog.current!
    element.showModal()
    return () => element.close()
  }, [])
  const field = (key: keyof Filters, label: string, type = 'number', min?: number, max?: number) => <label>
    <span>{label}</span><input type={type} value={draft[key]} min={min} max={max} step={type === 'number' ? 'any' : 1}
      onChange={(event) => setDraft({ ...draft, [key]: event.target.value })} />
  </label>

  return <dialog className="filter-dialog" ref={dialog} aria-labelledby="filter-title" onCancel={onClose}>
    <form noValidate onSubmit={(event) => {
      event.preventDefault()
      const normalized = Object.fromEntries(Object.entries(draft).map(([key, value]) => [key, value.trim()])) as Filters
      const message = validateFilters(normalized)
      setError(message)
      if (!message) onApply(normalized)
    }}>
      <div className="filter-heading"><div><span className="eyebrow">Explore the catalogue</span><h2 id="filter-title">Filter earthquakes</h2></div><button type="button" className="plain-button" onClick={onClose} aria-label="Close filters">×</button></div>
      <div className="filter-fields">
        <fieldset><legend>Magnitude</legend><div className="field-pair">{field('min_magnitude', 'Minimum magnitude', 'number', -2, 10)}{field('max_magnitude', 'Maximum magnitude', 'number', -2, 10)}</div></fieldset>
        <fieldset><legend>Area</legend>
          <label><span>Region contains</span><input type="search" maxLength={120} value={draft.region} placeholder="e.g. Japan, Alaska, Indonesia" onChange={(event) => setDraft({ ...draft, region: event.target.value })} /></label>
          <label><span>Geographic preset</span><select value="" onChange={(event) => {
            const bounds = areas[event.target.value]
            setDraft({ ...draft, min_lon: bounds ? String(bounds[0]) : '', min_lat: bounds ? String(bounds[1]) : '', max_lon: bounds ? String(bounds[2]) : '', max_lat: bounds ? String(bounds[3]) : '' })
          }}><option value="" disabled>Choose a bounding box…</option><option value="world">Worldwide / clear bounds</option>{Object.keys(areas).map((area) => <option key={area}>{area}</option>)}</select></label>
          <p className="field-help">Presets are approximate rectangles, not country borders. Edit bounds for an exact rectangle.</p>
          <details><summary>Coordinate bounds{draft.min_lon ? ' · Active' : ' · Optional'}</summary><div className="field-pair">{field('min_lon', 'West longitude', 'number', -180, 180)}{field('max_lon', 'East longitude', 'number', -180, 180)}{field('min_lat', 'South latitude', 'number', -90, 90)}{field('max_lat', 'North latitude', 'number', -90, 90)}</div><p className="field-help">West greater than east crosses the 180° meridian.</p></details>
        </fieldset>
        <fieldset><legend>Time · UTC</legend>
          <div className="time-shortcuts" aria-label="Time presets">{[1, 7, 30].map((days) => <button type="button" key={days} onClick={() => setDraft({ ...draft, start_time: new Date(Date.now() - days * 86400000).toISOString().slice(0, 19), end_time: '' })}>Last {days === 1 ? '24 hours' : `${days} days`}</button>)}<button type="button" onClick={() => setDraft({ ...draft, start_time: '', end_time: '' })}>All time</button></div>
          <div className="field-pair">{field('start_time', 'From (UTC)', 'datetime-local')}{field('end_time', 'Until (UTC)', 'datetime-local')}</div>
          <p className="field-help">Inclusive bounds. Presets set the start at application time; leave the end empty for live arrivals.</p>
        </fieldset>
        <fieldset><legend>Depth · km</legend><div className="field-pair">{field('min_depth', 'Minimum depth (km)', 'number', -10, 1000)}{field('max_depth', 'Maximum depth (km)', 'number', -10, 1000)}</div><p className="field-help">Blank fields are unrestricted. A magnitude or depth range excludes events with an unknown value for that field.</p></fieldset>
      </div>
      <div className="filter-footer">{error && <p role="alert">{error}</p>}<div><button type="button" className="plain-button" onClick={() => { setDraft({ ...emptyFilters }); setError(null) }}>Reset fields</button><button type="submit" className="action-button">Apply filters</button></div></div>
    </form>
  </dialog>
}
