import { expect, test } from '@playwright/test'

let browserErrors: string[]

test.beforeEach(async ({ page }) => {
  browserErrors = []
  page.on('pageerror', (error) => browserErrors.push(error.message))
  await page.route('**/api/v1/earthquakes?*', async (route) => {
    const query = new URL(route.request().url()).searchParams
    const items = Array.from({ length: 45 }, (_, index) => ({
      event_id: `layout-${index}`, source: 'EMSC', source_action: 'create',
      event_time: '2026-10-03T01:00:00Z', source_updated_at: null,
      ingested_at: '2026-10-03T01:00:01Z', latitude: 10 + index / 10, longitude: 20 + index / 10,
      depth_km: 12.4, magnitude: index < 5 ? 5.2 : 2, magnitude_type: 'Mw', region: `Test Region ${index}`,
      source_catalog: null, persisted_at: '2026-10-03T01:00:02Z',
    })).filter((event) => !query.has('min_magnitude') || event.magnitude >= Number(query.get('min_magnitude')))
    await route.fulfill({ json: { items, next_cursor: null, latest_change_cursor: 4 } })
  })
  await page.route('**/api/v1/earthquakes/changes?*', (route) => route.fulfill({ json: { items: [], next_cursor: null } }))
  await page.route('**/api/v1/earthquakes/stream?*', (route) => route.fulfill({ contentType: 'text/event-stream', body: ': connected\n\n' }))
})

test.afterEach(() => { expect(browserErrors).toEqual([]) })

test('desktop results scroll independently and filters query the catalogue', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/')
  await expect(page.getByRole('button', { name: /Test Region 44/ })).toBeAttached()
  const scroller = page.getByLabel('Earthquake results')
  await scroller.hover()
  await page.mouse.wheel(0, 700)
  await expect.poll(() => scroller.evaluate((element) => element.scrollTop)).toBeGreaterThan(0)
  expect(await page.evaluate(() => ({ height: document.documentElement.scrollHeight, viewport: innerHeight, scroll: scrollY }))).toEqual({ height: 900, viewport: 900, scroll: 0 })
  await page.getByRole('button', { name: 'Filters', exact: true }).click()
  await page.getByLabel('Minimum magnitude').fill('4')
  await page.screenshot({ path: 'test-results/filters-desktop.png' })
  const request = page.waitForRequest((request) => request.url().includes('/earthquakes?') && request.url().includes('min_magnitude=4'))
  await page.getByRole('button', { name: 'Apply filters' }).click()
  await request
  await expect(page.getByRole('button', { name: /Test Region 44/ })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /Test Region 4 / })).toBeVisible()
  await page.getByRole('button', { name: 'Recenter map' }).click()
  await page.screenshot({ path: 'test-results/catalogue-desktop.png' })
})

test('mobile map, results and details stay in one viewport and filters close with Escape', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Recenter map' })).toBeVisible()
  await page.getByRole('button', { name: 'events', exact: true }).click()
  await expect(page.getByRole('button', { name: /Test Region 0 / })).toBeVisible()
  await page.getByRole('button', { name: 'Filters', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.screenshot({ path: 'test-results/filters-mobile.png' })
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('button', { name: /Test Region 0 / }).click()
  await expect(page.getByRole('button', { name: 'map', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: 'details', exact: true }).click()
  await expect(page.getByText('layout-0')).toBeVisible()
  await page.getByRole('button', { name: 'events', exact: true }).click()
  const scroller = page.getByLabel('Earthquake results')
  await scroller.hover()
  await page.mouse.wheel(0, 700)
  await expect.poll(() => scroller.evaluate((element) => element.scrollTop)).toBeGreaterThan(0)
  expect(await page.evaluate(() => ({ height: document.documentElement.scrollHeight, width: document.documentElement.scrollWidth, viewport: innerHeight }))).toEqual({ height: 844, width: 390, viewport: 844 })
  await page.screenshot({ path: 'test-results/catalogue-mobile.png' })
})
