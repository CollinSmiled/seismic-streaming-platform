import { useEffect, useRef } from 'react'
import mapboxgl from 'mapbox-gl'
import type { Earthquake } from './api'
import { earthquakeFeatures } from './mapFeatures'
import { eventBounds } from './mapBounds'
import 'mapbox-gl/dist/mapbox-gl.css'

const sourceId = 'earthquakes'
const layerId = 'earthquake-points'

interface Props {
  events: Earthquake[]
  selectedId: string | null
  focus: { id: string, sequence: number } | null
  recenter?: number
  onSelect: (eventId: string) => void
}

export default function EarthquakeMap({ events, selectedId, focus, recenter = 0, onSelect }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<mapboxgl.Map | null>(null)
  const select = useRef(onSelect)
  const features = useRef(earthquakeFeatures(events, selectedId))
  const latestEvents = useRef(events)
  const latestFocus = useRef(focus)
  const ready = useRef(false)
  const focusedSequence = useRef(0)
  const latestRecenter = useRef(recenter)
  const centeredSequence = useRef(0)
  const token = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN

  function moveToFocus() {
    const target = latestFocus.current
    const current = map.current
    if (!ready.current || !target || !current || focusedSequence.current === target.sequence) return
    const event = latestEvents.current.find((item) => item.event_id === target.id)
    if (!event) return
    const camera = { center: [event.longitude, Math.max(-85, Math.min(85, event.latitude))] as [number, number], zoom: Math.max(current.getZoom(), 5) }
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) current.jumpTo(camera)
    else current.easeTo({ ...camera, duration: 850 })
    focusedSequence.current = target.sequence
  }

  function recenterMap() {
    const current = map.current
    if (!ready.current || !current || latestRecenter.current === centeredSequence.current) return
    const bounds = eventBounds(latestEvents.current)
    const duration = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 0 : 650
    if (bounds) current.fitBounds(bounds, { padding: 60, maxZoom: 6, duration })
    else current.easeTo({ center: [0, 15], zoom: 1.4, duration })
    centeredSequence.current = latestRecenter.current
  }

  useEffect(() => { select.current = onSelect }, [onSelect])

  useEffect(() => {
    if (!token || !container.current) return
    const instance = new mapboxgl.Map({
      container: container.current,
      accessToken: token,
      style: 'mapbox://styles/mapbox/light-v11',
      center: [0, 15],
      zoom: 1.4,
    })
    map.current = instance
    instance.on('load', () => {
      ready.current = true
      instance.addSource(sourceId, { type: 'geojson', data: features.current })
      instance.addLayer({
        id: layerId,
        type: 'circle',
        source: sourceId,
        paint: {
          'circle-radius': ['case', ['get', 'selected'], 10, 7],
          'circle-color': ['case', ['get', 'selected'], '#f0c020', '#d02020'],
          'circle-stroke-color': '#121212',
          'circle-stroke-width': 2.5,
        },
      })
      instance.on('click', layerId, (event) => {
        const id = (event.features?.[0] as { properties?: { event_id?: unknown } } | undefined)?.properties?.event_id
        if (typeof id === 'string') select.current(id)
      })
      instance.on('mouseenter', layerId, () => { instance.getCanvas().style.cursor = 'pointer' })
      instance.on('mouseleave', layerId, () => { instance.getCanvas().style.cursor = '' })
      moveToFocus()
      recenterMap()
    })
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => instance.resize()) : null
    observer?.observe(container.current)
    return () => { observer?.disconnect(); ready.current = false; focusedSequence.current = 0; centeredSequence.current = 0; map.current = null; instance.remove() }
  }, [token])

  useEffect(() => {
    latestEvents.current = events
    latestFocus.current = focus
    latestRecenter.current = recenter
    features.current = earthquakeFeatures(events, selectedId)
    const source = map.current?.getSource(sourceId) as mapboxgl.GeoJSONSource | undefined
    source?.setData(features.current)
    moveToFocus()
    recenterMap()
  }, [events, selectedId, focus, recenter])

  if (!token) {
    return <div className="map-setup" role="status">Set <code>VITE_MAPBOX_ACCESS_TOKEN</code> in <code>frontend/.env.local</code> to display the map. The event list remains available.</div>
  }
  return <div className="map-canvas" ref={container} role="img" aria-label="Map of earthquake locations" />
}
