import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { fetchChanges, fetchEarthquakes } from './api'
import type { Earthquake, EarthquakeChange } from './api'
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
  const [focus, setFocus] = useState<{ id: string, sequence: number } | null>(null)
  const [liveStart, setLiveStart] = useState<number | null>(null)
  const [liveStatus, setLiveStatus] = useState<'connecting' | 'live' | 'reconnecting'>('connecting')
  const [unreadIds, setUnreadIds] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const lastCursor = useRef(0)
  const eventCursors = useRef(new Map<string, number>())
  const knownIds = useRef(new Set<string>())
  const selected = events.find((event) => event.event_id === selectedId) ?? events[0]

  function focusEvent(id: string) {
    setSelectedId(id)
    setFocus((previous) => ({ id, sequence: (previous?.sequence ?? 0) + 1 }))
    setUnreadIds((previous) => previous.filter((unread) => unread !== id))
  }

  function applyChange(change: EarthquakeChange) {
    const id = change.event.event_id
    if (change.cursor <= (eventCursors.current.get(id) ?? 0)) return
    eventCursors.current.set(id, change.cursor)
    lastCursor.current = Math.max(lastCursor.current, change.cursor)
    const isNew = change.kind === 'created' && !knownIds.current.has(id)
    knownIds.current.add(id)
    setEvents((previous) => {
      const updated = [change.event, ...previous.filter((event) => event.event_id !== id)]
      return updated.sort((left, right) => right.event_time.localeCompare(left.event_time) || right.event_id.localeCompare(left.event_id))
    })
    if (isNew) setUnreadIds((previous) => [id, ...previous])
  }

  async function load(cursor?: string, signal?: AbortSignal) {
    setLoading(true)
    setError(null)
    try {
      const page = await fetchEarthquakes(cursor, signal)
      if (cursor) {
        setEvents((previous) => {
          const existing = new Set(previous.map((event) => event.event_id))
          return [...previous, ...page.items.filter((event) => !existing.has(event.event_id))]
        })
        page.items.forEach((event) => knownIds.current.add(event.event_id))
      } else {
        setEvents(page.items)
        knownIds.current = new Set(page.items.map((event) => event.event_id))
        eventCursors.current.clear()
        lastCursor.current = page.latest_change_cursor
        setLiveStart(page.latest_change_cursor)
        setUnreadIds([])
      }
      setNextCursor(page.next_cursor)
      if (!cursor) setSelectedId(page.items[0]?.event_id ?? null)
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
        setSelectedId(page.items[0]?.event_id ?? null)
        knownIds.current = new Set(page.items.map((event) => event.event_id))
        lastCursor.current = page.latest_change_cursor
        setLiveStart(page.latest_change_cursor)
      })
      .catch((cause: unknown) => {
        if (cause instanceof Error && cause.name === 'AbortError') return
        setError(cause instanceof Error ? cause.message : 'Unable to load earthquakes')
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (liveStart === null || typeof EventSource === 'undefined') return
    let active = true
    let source: EventSource | null = null
    let retry: ReturnType<typeof setTimeout> | null = null
    let attempts = 0
    const controller = new AbortController()

    function connect() {
      if (!active) return
      const start = lastCursor.current
      setLiveStatus(attempts === 0 ? 'connecting' : 'reconnecting')
      const current = new EventSource(`/api/v1/earthquakes/stream?after=${start}`)
      source = current
      current.addEventListener('earthquake', (message) => {
        try { applyChange(JSON.parse((message as MessageEvent).data) as EarthquakeChange) }
        catch { setLiveStatus('reconnecting') }
      })
      current.onopen = () => {
        attempts = 0
        setLiveStatus('live')
        // The stream and this read can overlap. Per-event cursors make repeats harmless.
        void (async () => {
          let after = start
          try {
            while (active) {
              const page = await fetchChanges(after, controller.signal)
              page.items.forEach(applyChange)
              if (page.next_cursor === null) break
              after = page.next_cursor
            }
          } catch { if (active) setLiveStatus('reconnecting') }
        })()
      }
      current.onerror = () => {
        current.close()
        if (source === current) source = null
        if (!active) return
        setLiveStatus('reconnecting')
        attempts += 1
        retry = setTimeout(connect, Math.min(1000 * 2 ** attempts, 30000))
      }
    }
    connect()
    return () => {
      active = false
      controller.abort()
      if (retry) clearTimeout(retry)
      source?.close()
    }
  }, [liveStart])

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
              <button type="button" className={event.event_id === selected?.event_id ? 'event-row selected' : 'event-row'} onClick={() => focusEvent(event.event_id)} aria-pressed={event.event_id === selected?.event_id}>
                <span className="magnitude">{event.magnitude === null ? 'M —' : `M ${event.magnitude.toFixed(1)}`}</span>
                <span className="event-summary"><strong>{event.region || 'Unnamed region'}</strong><span>{utcTime(event.event_time)}</span></span>
              </button>
            </li>)}
          </ul>}
          {nextCursor && <button type="button" className="load-more" disabled={loading} onClick={() => void load(nextCursor)}>{loading ? 'Loading…' : 'Load more'}</button>}
        </section>
        <section className="map-panel" aria-label="Earthquake map">
          <div className="map-heading"><h2>Epicenter map</h2><span>{liveStatus === 'live' ? 'Live updates' : liveStatus === 'connecting' ? 'Connecting' : 'Reconnecting'}</span></div>
          <div className="map-viewport">
            <Suspense fallback={<p className="panel-message">Loading map…</p>}>
              <EarthquakeMap events={events} selectedId={selected?.event_id ?? null} focus={focus} onSelect={setSelectedId} />
            </Suspense>
            {unreadIds.length > 0 && <div className="new-event-notice" role="status">
              <span className="notice-symbol" aria-hidden="true">●</span>
              <div><strong>{unreadIds.length} new {unreadIds.length === 1 ? 'earthquake' : 'earthquakes'}</strong><span>New event data is ready</span></div>
              <button type="button" onClick={() => focusEvent(unreadIds[0])}>View latest</button>
              <button type="button" className="notice-dismiss" onClick={() => setUnreadIds([])} aria-label="Dismiss new earthquake notice">×</button>
            </div>}
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
