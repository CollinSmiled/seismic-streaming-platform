import { lazy, Suspense, useEffect, useState } from 'react'
import { fetchEarthquakes } from './api'
import type { Earthquake } from './api'
import './App.css'

const EarthquakeMap = lazy(() => import('./EarthquakeMap'))

const utcTime = (value: string) => new Intl.DateTimeFormat('en-GB', {
  dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC',
}).format(new Date(value)) + ' UTC'

function BrandMark() {
  return <span className="brand-mark" aria-hidden="true">
    <span className="brand-circle" />
    <span className="brand-square" />
    <span className="brand-triangle" />
  </span>
}

function App() {
  const [events, setEvents] = useState<Earthquake[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const selected = events.find((event) => event.event_id === selectedId) ?? events[0]

  async function load(cursor?: string, signal?: AbortSignal) {
    setLoading(true)
    setError(null)
    try {
      const page = await fetchEarthquakes(cursor, signal)
      setEvents((previous) => cursor ? [...previous, ...page.items] : page.items)
      setNextCursor(page.next_cursor)
      if (!cursor) setSelectedId(null)
    } catch (cause) {
      if (cause instanceof Error && cause.name === 'AbortError') return
      setError(cause instanceof Error ? cause.message : 'Unable to load earthquakes')
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }

  useEffect(() => {
    const controller = new AbortController()
    void fetchEarthquakes(undefined, controller.signal)
      .then((page) => {
        setEvents(page.items)
        setNextCursor(page.next_cursor)
      })
      .catch((cause: unknown) => {
        if (cause instanceof Error && cause.name === 'AbortError') return
        setError(cause instanceof Error ? cause.message : 'Unable to load earthquakes')
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [])

  return (
    <main className="app">
      <header className="app-header">
        <div className="brand"><BrandMark /><h1>SEISMIC <span>STREAM</span></h1></div>
        <div className="header-actions">
          <span className="view-label">Earthquake catalogue</span>
          <button type="button" className="action-button" onClick={() => void load()} disabled={loading}>Refresh data</button>
        </div>
      </header>
      <div className="workspace">
        <section className="event-panel" aria-labelledby="events-heading">
          <div className="section-heading">
            <h2 id="events-heading">Earthquakes</h2>
            <span className="event-count" aria-label={`${events.length} ${events.length === 1 ? 'event' : 'events'} shown`}>{events.length}</span>
          </div>
          {loading && events.length === 0 && <p role="status" className="panel-message">Loading earthquakes…</p>}
          {error && <p role="alert" className="panel-message error">{error}. Check that the API and PostgreSQL are running.</p>}
          {!loading && !error && events.length === 0 && <p className="panel-message">No earthquakes are stored yet. Publish a fixture and run the processor to populate the map.</p>}
          {events.length > 0 && <ul className="event-list">
            {events.map((event) => <li key={event.event_id}>
              <button type="button" className={event.event_id === selected?.event_id ? 'event-row selected' : 'event-row'} onClick={() => setSelectedId(event.event_id)} aria-pressed={event.event_id === selected?.event_id}>
                <span className="magnitude">{event.magnitude === null ? 'M —' : `M ${event.magnitude.toFixed(1)}`}</span>
                <span className="event-summary"><strong>{event.region || 'Unnamed region'}</strong><span>{utcTime(event.event_time)}</span></span>
              </button>
            </li>)}
          </ul>}
          {nextCursor && <button type="button" className="load-more" disabled={loading} onClick={() => void load(nextCursor)}>{loading ? 'Loading…' : 'Load more'}</button>}
        </section>
        <section className="map-panel" aria-label="Earthquake map">
          <div className="map-heading"><h2>Epicenter map</h2><span>Historical view</span></div>
          <div className="map-viewport">
            <Suspense fallback={<p className="panel-message">Loading map…</p>}>
              <EarthquakeMap events={events} selectedId={selected?.event_id ?? null} onSelect={setSelectedId} />
            </Suspense>
            <div className="attribution">Earthquake data: <a href="https://www.seismicportal.eu/" target="_blank" rel="noreferrer">EMSC-CSEM SeismicPortal</a></div>
          </div>
        </section>
        <aside className="detail-panel" aria-labelledby="detail-heading">
          <h2 id="detail-heading">Event details</h2>
          {selected ? <><div className="detail-feature">
            <span className="detail-value">{selected.magnitude === null ? '—' : selected.magnitude.toFixed(1)}</span>
            <span className="detail-magnitude-label">Magnitude {selected.magnitude_type ?? ''}</span>
            <strong>{selected.region || 'Unnamed region'}</strong>
          </div><dl>
            <div><dt>Time</dt><dd>{utcTime(selected.event_time)}</dd></div>
            <div><dt>Coordinates</dt><dd>{selected.latitude.toFixed(3)}°, {selected.longitude.toFixed(3)}°</dd></div>
            <div><dt>Depth</dt><dd>{selected.depth_km === null ? 'Unknown' : `${selected.depth_km.toFixed(1)} km`}</dd></div>
            <div><dt>EMSC ID</dt><dd className="event-id">{selected.event_id}</dd></div>
          </dl></> : <p>Select an event to see its details.</p>}
        </aside>
      </div>
    </main>
  )
}

export default App
