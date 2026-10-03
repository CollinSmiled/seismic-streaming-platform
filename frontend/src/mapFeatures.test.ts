import { describe, expect, it } from 'vitest'
import { earthquakeFeatures } from './mapFeatures'
import type { Earthquake } from './api'

describe('earthquakeFeatures', () => {
  it('places an API event at longitude, latitude and marks the selected ID', () => {
    const event = { event_id: 'emsc-123', longitude: 20.25, latitude: 10.5 } as Earthquake
    const result = earthquakeFeatures([event], 'emsc-123')
    expect(result.features).toEqual([{
      type: 'Feature', id: 'emsc-123',
      properties: { event_id: 'emsc-123', selected: true },
      geometry: { type: 'Point', coordinates: [20.25, 10.5] },
    }])
  })
})
