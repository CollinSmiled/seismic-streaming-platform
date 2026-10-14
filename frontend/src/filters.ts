import type { Earthquake } from './api'

export const emptyFilters = {
  region: '', min_magnitude: '', max_magnitude: '', min_depth: '', max_depth: '',
  start_time: '', end_time: '', min_lon: '', min_lat: '', max_lon: '', max_lat: '',
}
export type Filters = typeof emptyFilters
export const boundsKeys = ['min_lon', 'min_lat', 'max_lon', 'max_lat'] as const
export const numberRanges = [
  ['min_magnitude', 'max_magnitude', -2, 10, 'Magnitude'],
  ['min_depth', 'max_depth', -10, 1000, 'Depth'],
  ['min_lat', 'max_lat', -90, 90, 'Latitude'],
  ['min_lon', 'max_lon', -180, 180, 'Longitude'],
] as const

export function validateFilters(filters: Filters): string | null {
  for (const [min, max, lower, upper, name] of numberRanges) {
    for (const key of [min, max]) {
      if (filters[key] && (!Number.isFinite(Number(filters[key])) || Number(filters[key]) < lower || Number(filters[key]) > upper)) return `${name} must be between ${lower} and ${upper}.`
    }
    if (name !== 'Longitude' && filters[min] && filters[max] && Number(filters[min]) > Number(filters[max])) return `Minimum ${name.toLowerCase()} must not exceed maximum.`
  }
  if (boundsKeys.some((key) => filters[key]) && !boundsKeys.every((key) => filters[key])) return 'Enter all four geographic bounds.'
  for (const key of ['start_time', 'end_time'] as const) {
    if (filters[key] && !Number.isFinite(Date.parse(`${filters[key]}Z`))) return 'Enter valid UTC dates.'
  }
  if (filters.start_time && filters.end_time && filters.start_time > filters.end_time) return 'Start time must not exceed end time.'
  return null
}

export function filterQuery(filters: Filters): URLSearchParams {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (!value.trim()) continue
    query.set(key, key.endsWith('_time') ? new Date(`${value}Z`).toISOString() : value.trim())
  }
  return query
}

export function matchesFilters(event: Earthquake, filters: Filters): boolean {
  if (filters.region && !(event.region ?? '').toLowerCase().includes(filters.region.trim().toLowerCase())) return false
  for (const [min, max, value] of [
    ['min_magnitude', 'max_magnitude', event.magnitude],
    ['min_depth', 'max_depth', event.depth_km],
  ] as const) {
    if ((filters[min] || filters[max]) && value === null) return false
    if (value !== null && ((filters[min] && value < Number(filters[min])) || (filters[max] && value > Number(filters[max])))) return false
  }
  const time = Date.parse(event.event_time)
  if (filters.start_time && time < Date.parse(`${filters.start_time}Z`)) return false
  if (filters.end_time && time > Date.parse(`${filters.end_time}Z`)) return false
  if (boundsKeys.every((key) => filters[key])) {
    const west = Number(filters.min_lon), east = Number(filters.max_lon)
    if (event.latitude < Number(filters.min_lat) || event.latitude > Number(filters.max_lat)) return false
    if (west <= east ? event.longitude < west || event.longitude > east : event.longitude < west && event.longitude > east) return false
  }
  return true
}

export function filterLabels(filters: Filters): string[] {
  const labels: string[] = []
  if (filters.region.trim()) labels.push(`Region: ${filters.region.trim()}`)
  if (filters.min_magnitude || filters.max_magnitude) labels.push(`M ${filters.min_magnitude || '−2'} to ${filters.max_magnitude || '10'}`)
  if (filters.min_depth || filters.max_depth) labels.push(`Depth ${filters.min_depth || '−10'} to ${filters.max_depth || '1000'} km`)
  if (filters.start_time || filters.end_time) labels.push('UTC time range')
  if (filters.min_lon) labels.push('Geographic bounds')
  return labels
}
