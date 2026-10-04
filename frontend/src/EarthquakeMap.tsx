import { useEffect, useRef } from 'react'
import mapboxgl from 'mapbox-gl'
import type { Earthquake } from './api'
import { earthquakeFeatures } from './mapFeatures'
import 'mapbox-gl/dist/mapbox-gl.css'

const sourceId = 'earthquakes'
const layerId = 'earthquake-points'

interface Props {
  events: Earthquake[]
  selectedId: string | null
  onSelect: (eventId: string) => void
}

export default function EarthquakeMap({ events, selectedId, onSelect }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<mapboxgl.Map | null>(null)
  const select = useRef(onSelect)
  const features = useRef(earthquakeFeatures(events, selectedId))
  const token = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN

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
    })
    return () => { map.current = null; instance.remove() }
  }, [token])

  useEffect(() => {
    features.current = earthquakeFeatures(events, selectedId)
    const source = map.current?.getSource(sourceId) as mapboxgl.GeoJSONSource | undefined
    source?.setData(features.current)
  }, [events, selectedId])

  if (!token) {
    return <div className="map-setup" role="status">Set <code>VITE_MAPBOX_ACCESS_TOKEN</code> in <code>frontend/.env.local</code> to display the map. The event list remains available.</div>
  }
  return <div className="map-canvas" ref={container} role="img" aria-label="Map of earthquake locations" />
}
