import { describe, expect, it } from 'vitest'
import type { Earthquake } from './api'
import { emptyFilters, filterQuery, matchesFilters, validateFilters } from './filters'
import { eventBounds } from './mapBounds'

const event = { region: 'Island_100%', magnitude: 5, depth_km: 30, latitude: 10, longitude: -179, event_time: '2026-10-03T01:00:00Z' } as Earthquake
describe('earthquake filtering', () => {
  it('uses inclusive ranges, UTC times and literal region matching', () => {
    const filters = { ...emptyFilters, min_magnitude: '5', max_magnitude: '5', max_depth: '30', region: 'ISLAND_', start_time: '2026-10-03T01:00', end_time: '2026-10-03T01:00' }
    expect(matchesFilters(event, filters)).toBe(true)
    expect(filterQuery(filters).get('start_time')).toBe('2026-10-03T01:00:00.000Z')
    expect(matchesFilters({ ...event, magnitude: null }, filters)).toBe(false)
    expect(matchesFilters({ ...event, depth_km: null }, filters)).toBe(false)
    expect(matchesFilters({ ...event, depth_km: null, magnitude: null }, emptyFilters)).toBe(true)
    expect(matchesFilters({ ...event, event_time: '2026-10-03T01:00:01Z' }, filters)).toBe(false)
  })
  it('handles Pacific bounds and rejects incomplete or reversed bounds', () => {
    const filters = { ...emptyFilters, min_lon: '170', max_lon: '-170', min_lat: '5', max_lat: '15' }
    expect(validateFilters(filters)).toBeNull()
    expect(matchesFilters(event, filters)).toBe(true)
    expect(matchesFilters({ ...event, longitude: 179 }, filters)).toBe(true)
    expect(matchesFilters({ ...event, longitude: 0 }, filters)).toBe(false)
    expect(validateFilters({ ...filters, max_lat: '' })).toContain('four')
    expect(validateFilters({ ...filters, max_lat: '1' })).toContain('Minimum latitude')
    expect(validateFilters({ ...emptyFilters, min_depth: 'NaN' })).toContain('Depth')
  })
})
describe('map recenter bounds', () => {
  it('fits the shortest longitude arc across the antimeridian', () => {
    expect(eventBounds([event, { ...event, latitude: 20, longitude: 179 }])).toEqual([[179, 10], [181, 20]])
    expect(eventBounds([event])).toEqual([[-179, 10], [-179, 10]])
    expect(eventBounds([])).toBeNull()
  })
})
