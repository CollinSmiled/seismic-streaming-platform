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
  latest_change_cursor: number
}

export interface EarthquakeChange {
  cursor: number
  kind: 'created' | 'updated'
  event: Earthquake
}

export interface ChangePage {
  items: EarthquakeChange[]
  next_cursor: number | null
}

export async function fetchEarthquakes(cursor?: string, signal?: AbortSignal): Promise<EarthquakePage> {
  const query = new URLSearchParams({ limit: '100' })
  if (cursor) query.set('cursor', cursor)
  const response = await fetch(`/api/v1/earthquakes?${query}`, { signal })
  if (!response.ok) throw new Error(`Earthquake request failed (${response.status})`)
  return response.json() as Promise<EarthquakePage>
}

export async function fetchChanges(after: number, signal?: AbortSignal): Promise<ChangePage> {
  const query = new URLSearchParams({ after: String(after), limit: '100' })
  const response = await fetch(`/api/v1/earthquakes/changes?${query}`, { signal })
  if (!response.ok) throw new Error(`Change request failed (${response.status})`)
  return response.json() as Promise<ChangePage>
}
