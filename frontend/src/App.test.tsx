import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import type { Earthquake, EarthquakeChange, EarthquakePage } from './api'

const event: Earthquake = {
  event_id: 'emsc-123', source: 'EMSC', source_action: 'create',
  event_time: '2026-10-03T01:00:00Z', source_updated_at: null,
  ingested_at: '2026-10-03T01:00:01Z', latitude: 10.5, longitude: 20.25,
  depth_km: 12.4, magnitude: 5.2, magnitude_type: 'Mw', region: 'Test Region',
  source_catalog: null, persisted_at: '2026-10-03T01:00:02Z',
}

class FakeEventSource {
  static instances: FakeEventSource[] = []
  onopen: ((event: Event) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  private earthquakeListener: ((event: Event) => void) | null = null
  url: string
  constructor(url: string) { this.url = url; FakeEventSource.instances.push(this) }
  addEventListener(type: string, listener: EventListenerOrEventListenerObject) {
    if (type === 'earthquake' && typeof listener === 'function') this.earthquakeListener = listener
  }
  emit(change: EarthquakeChange) { this.earthquakeListener?.(new MessageEvent('earthquake', { data: JSON.stringify(change) })) }
  close() {}
}

beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: function (this: HTMLDialogElement) { this.setAttribute('open', '') } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value: function (this: HTMLDialogElement) { this.removeAttribute('open') } })
  vi.stubEnv('VITE_MAPBOX_ACCESS_TOKEN', '')
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ items: [event], next_cursor: null, latest_change_cursor: 4 }),
  }))
  FakeEventSource.instances = []
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.unstubAllEnvs() })

describe('App', () => {
  it('ignores a superseded catalogue response after filters change', async () => {
    let complete!: (response: Response) => void
    vi.mocked(fetch).mockReturnValueOnce(new Promise<Response>((resolve) => { complete = resolve }))
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Filters' }))
    fireEvent.change(screen.getByLabelText('Minimum magnitude'), { target: { value: '5' } })
    fireEvent.submit(screen.getByRole('button', { name: 'Apply filters' }).closest('form')!)
    await screen.findByText('M 5.2')
    const stale: EarthquakePage = { items: [{ ...event, event_id: 'stale', magnitude: 1 }], next_cursor: 'stale-page', latest_change_cursor: 2 }
    complete({ ok: true, json: async () => stale } as Response)
    await waitFor(() => expect(screen.queryByText('M 1.0')).toBeNull())
    expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull()
    expect(screen.getByText('M 5.2')).toBeDefined()
  })

  it('queries catalogue filters on every page, validates ranges and clears them', async () => {
    vi.mocked(fetch).mockResolvedValue({ ok: true, json: async () => ({ items: [event], next_cursor: 'page-two', latest_change_cursor: 4 }) } as Response)
    render(<App />)
    await screen.findByText('M 5.2')
    fireEvent.click(screen.getByRole('button', { name: 'Filters' }))
    fireEvent.change(screen.getByLabelText('Minimum magnitude'), { target: { value: '6' } })
    fireEvent.change(screen.getByLabelText('Maximum magnitude'), { target: { value: '5' } })
    fireEvent.submit(screen.getByRole('button', { name: 'Apply filters' }).closest('form')!)
    expect(screen.getByRole('alert').textContent).toContain('Minimum magnitude')
    fireEvent.change(screen.getByLabelText('Minimum magnitude'), { target: { value: '4' } })
    fireEvent.change(screen.getByLabelText('Region contains'), { target: { value: 'Test' } })
    fireEvent.submit(screen.getByRole('button', { name: 'Apply filters' }).closest('form')!)
    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/v1/earthquakes?limit=100&region=Test&min_magnitude=4&max_magnitude=5', expect.anything()))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Load more' }).hasAttribute('disabled')).toBe(false))
    fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/v1/earthquakes?limit=100&cursor=page-two&region=Test&min_magnitude=4&max_magnitude=5', expect.anything()))
    fireEvent.click(screen.getByRole('button', { name: 'Clear all' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Filters' })).toBeDefined())
  })

  it('filters live notices and removes a revised event that leaves the filter', async () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    render(<App />)
    await screen.findByText('M 5.2')
    fireEvent.click(screen.getByRole('button', { name: 'Filters' }))
    fireEvent.change(screen.getByLabelText('Minimum magnitude'), { target: { value: '5' } })
    fireEvent.submit(screen.getByRole('button', { name: 'Apply filters' }).closest('form')!)
    await waitFor(() => expect(FakeEventSource.instances.length).toBeGreaterThan(1))
    const source = FakeEventSource.instances.at(-1)!
    source.emit({ cursor: 5, kind: 'created', event: { ...event, event_id: 'small', magnitude: 2 } })
    expect(screen.queryByText('1 new earthquake')).toBeNull()
    source.emit({ cursor: 6, kind: 'created', event: { ...event, event_id: 'large', magnitude: 6 } })
    await screen.findByText('1 new earthquake')
    source.emit({ cursor: 7, kind: 'updated', event: { ...event, event_id: 'large', magnitude: 4 } })
    await waitFor(() => expect(screen.queryByText('M 6.0')).toBeNull())
    expect(screen.queryByText('1 new earthquake')).toBeNull()
  })

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

  it('shows a notice for a new live event and opens it on request', async () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    const newest = { ...event, event_id: 'emsc-456', region: 'New Region', magnitude: 6.1 }
    render(<App />)
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    expect(FakeEventSource.instances[0].url).toBe('/api/v1/earthquakes/stream?after=4')
    FakeEventSource.instances[0].emit({ cursor: 5, kind: 'created', event: newest })
    await waitFor(() => expect(screen.getByText('1 new earthquake')).toBeDefined())
    fireEvent.click(screen.getByRole('button', { name: 'View latest' }))
    expect(screen.queryByText('1 new earthquake')).toBeNull()
    expect(screen.getByText('emsc-456')).toBeDefined()
    FakeEventSource.instances[0].emit({ cursor: 6, kind: 'updated', event: { ...newest, magnitude: 6.2 } })
    await waitFor(() => expect(screen.getByText('M 6.2')).toBeDefined())
    expect(screen.queryByText('1 new earthquake')).toBeNull()
  })

  it('catches up after the stream opens without duplicating live events', async () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    const missed = { ...event, event_id: 'emsc-missed', region: 'Missed Region' }
    vi.mocked(fetch).mockImplementation(async (input) => ({
      ok: true,
      json: async () => String(input).includes('/changes?')
        ? { items: [{ cursor: 5, kind: 'created', event: missed }], next_cursor: null }
        : { items: [event], next_cursor: null, latest_change_cursor: 4 },
    }) as Response)
    render(<App />)
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    FakeEventSource.instances[0].onopen?.(new Event('open'))
    await waitFor(() => expect(screen.getByText('1 new earthquake')).toBeDefined())
    FakeEventSource.instances[0].emit({ cursor: 5, kind: 'created', event: missed })
    expect(screen.getAllByRole('button', { name: /Missed Region/ })).toHaveLength(1)
  })
})
