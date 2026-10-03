import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import type { Earthquake } from './api'

const event: Earthquake = {
  event_id: 'emsc-123', source: 'EMSC', source_action: 'create',
  event_time: '2026-10-03T01:00:00Z', source_updated_at: null,
  ingested_at: '2026-10-03T01:00:01Z', latitude: 10.5, longitude: 20.25,
  depth_km: 12.4, magnitude: 5.2, magnitude_type: 'Mw', region: 'Test Region',
  source_catalog: null, persisted_at: '2026-10-03T01:00:02Z',
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ items: [event], next_cursor: null }),
  }))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('App', () => {
  it('credits the upstream earthquake data source', () => {
    render(<App />)

    expect(
      screen.getByRole('link', { name: 'EMSC-CSEM SeismicPortal' }).getAttribute('href'),
    ).toBe('https://www.seismicportal.eu/')
  })

  it('shows an API earthquake in the list and detail panel', async () => {
    render(<App />)
    await waitFor(() => expect(screen.getAllByText('Test Region', { selector: 'strong' })).toHaveLength(2))
    expect(screen.getByText('M 5.2')).toBeDefined()
    expect(screen.getByText('10.500°, 20.250°')).toBeDefined()
    expect(screen.getByText('emsc-123')).toBeDefined()
    expect(fetch).toHaveBeenCalledWith('/api/v1/earthquakes?limit=100', expect.anything())
  })

  it('reports an API outage and retries on refresh', async () => {
    vi.mocked(fetch).mockResolvedValueOnce({ ok: false, status: 503 } as Response)
    render(<App />)
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('503'))
    fireEvent.click(screen.getByRole('button', { name: 'Refresh data' }))
    await waitFor(() => expect(screen.getAllByText('Test Region', { selector: 'strong' })).toHaveLength(2))
  })
})
