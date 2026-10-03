export interface Earthquake {
  event_id: string
  source: string
  source_action: string | null
  event_time: string
  source_updated_at: string | null
  ingested_at: string
  latitude: number
  longitude: number
  depth_km: number | null
  magnitude: number | null
  magnitude_type: string | null
  region: string | null
  source_catalog: string | null
  persisted_at: string
}

export interface EarthquakePage {
  items: Earthquake[]
  next_cursor: string | null
}

export async function fetchEarthquakes(cursor?: string, signal?: AbortSignal): Promise<EarthquakePage> {
  const query = new URLSearchParams({ limit: '100' })
  if (cursor) query.set('cursor', cursor)
  const response = await fetch(`/api/v1/earthquakes?${query}`, { signal })
  if (!response.ok) throw new Error(`Earthquake request failed (${response.status})`)
  return response.json() as Promise<EarthquakePage>
}
