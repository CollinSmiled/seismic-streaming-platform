import { execFileSync } from 'node:child_process'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'

const directory = path.dirname(fileURLToPath(import.meta.url))
const backend = path.resolve(directory, '../../backend')
const capture = path.join(backend, 'tests/fixtures/emsc_catalogue_capture.json')
const python = path.join(
  backend,
  '.venv',
  process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
)

test('a Kafka event appears in the browser and a new event raises a live notice', async ({ page, request }) => {
  await expect.poll(async () => {
    const response = await request.get('/api/v1/earthquakes?limit=100')
    if (!response.ok()) return false
    const body = await response.json() as { items: { event_id: string }[] }
    return body.items.some((event) => event.event_id === '20261003_0000205')
  }, { timeout: 30_000 }).toBe(true)

  await page.goto('/')
  await expect(page.getByRole('button', { name: /STRAIT OF GIBRALTAR/ })).toBeVisible()
  await page.getByRole('button', { name: /SWITZERLAND/ }).click()
  await expect(page.getByText('20261003_0000204')).toBeVisible()
  await expect(page.getByText('Live updates')).toBeVisible()

  const eventId = `browser-e2e-${Date.now()}`
  const timestamp = new Date().toISOString()
  const catalogue = JSON.parse(readFileSync(capture, 'utf8')) as {
    type: string
    features: { id: string, properties: Record<string, unknown> }[]
  }
  const feature = structuredClone(catalogue.features[0])
  feature.id = eventId
  feature.properties.unid = eventId
  feature.properties.time = timestamp
  feature.properties.lastupdate = timestamp
  feature.properties.flynn_region = 'BROWSER PIPELINE TEST'
  const output = path.resolve(directory, '../test-results/browser-fixture.json')
  mkdirSync(path.dirname(output), { recursive: true })
  writeFileSync(output, JSON.stringify({ type: 'FeatureCollection', features: [feature] }))

  execFileSync(python, [
    '-m', 'seismic_stream.ingestion.fixture_producer',
    '--fixture', output,
    '--ingested-at', timestamp,
    '--bootstrap-server', process.env.KAFKA_BOOTSTRAP_SERVERS ?? '127.0.0.1:9092',
    '--topic', process.env.E2E_KAFKA_TOPIC ?? 'earthquake.events.v1',
  ], { cwd: backend, timeout: 30_000 })

  await expect(page.getByText('1 new earthquake')).toBeVisible()
  await page.getByRole('button', { name: 'View latest' }).click()
  await expect(page.getByText(eventId)).toBeVisible()
  await expect(page.getByRole('link', { name: 'EMSC-CSEM SeismicPortal' })).toBeVisible()
})
