import type { FeatureCollection, Point } from 'geojson'
import type { Earthquake } from './api'

export function earthquakeFeatures(events: Earthquake[], selectedId: string | null): FeatureCollection<Point> {
  return {
    type: 'FeatureCollection',
    features: events.map((event) => ({
      type: 'Feature',
      id: event.event_id,
      properties: { event_id: event.event_id, selected: event.event_id === selectedId },
      geometry: { type: 'Point', coordinates: [event.longitude, event.latitude] },
    })),
  }
}
