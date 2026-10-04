import { cleanup, render, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import EarthquakeMap from './EarthquakeMap'
import type { Earthquake } from './api'

const { addSource, addLayer, remove, easeTo } = vi.hoisted(() => ({
  addSource: vi.fn(), addLayer: vi.fn(), remove: vi.fn(), easeTo: vi.fn(),
}))

vi.mock('mapbox-gl', () => ({
  default: {
    Map: class {
      on(name: string, ...args: unknown[]) {
        if (name === 'load') queueMicrotask(args[0] as () => void)
      }
      addSource = addSource
      addLayer = addLayer
      getSource() { return undefined }
      getZoom() { return 1.4 }
      easeTo = easeTo
      remove = remove
    },
  },
}))

afterEach(() => { cleanup(); vi.unstubAllEnvs(); vi.clearAllMocks() })

describe('EarthquakeMap', () => {
  it('adds an API earthquake to the Mapbox point source', async () => {
    vi.stubEnv('VITE_MAPBOX_ACCESS_TOKEN', 'pk.test')
    const event = { event_id: 'emsc-123', longitude: 20.25, latitude: 10.5 } as Earthquake
    const view = render(<EarthquakeMap events={[event]} selectedId="emsc-123" focus={null} onSelect={() => {}} />)
    await waitFor(() => expect(addSource).toHaveBeenCalledOnce())
    expect(addSource).toHaveBeenCalledWith('earthquakes', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [{
        type: 'Feature', id: 'emsc-123',
        properties: { event_id: 'emsc-123', selected: true },
        geometry: { type: 'Point', coordinates: [20.25, 10.5] },
      }] },
    })
    expect(addLayer).toHaveBeenCalledWith(expect.objectContaining({ type: 'circle' }))
    view.rerender(<EarthquakeMap events={[event]} selectedId="emsc-123" focus={{ id: 'emsc-123', sequence: 1 }} onSelect={() => {}} />)
    await waitFor(() => expect(easeTo).toHaveBeenCalledWith({ center: [20.25, 10.5], zoom: 5, duration: 850 }))
  })
})
