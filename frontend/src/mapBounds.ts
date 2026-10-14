import type { Earthquake } from './api'

// Use the shortest longitude arc so Pacific events don't fit almost the whole world.
export function eventBounds(events: Earthquake[]): [[number, number], [number, number]] | null {
  if (!events.length) return null
  const longitudes = events.map((event) => (event.longitude + 360) % 360).sort((a, b) => a - b)
  let gap = -1, start = 0
  for (let index = 0; index < longitudes.length; index += 1) {
    const next = index === longitudes.length - 1 ? longitudes[0] + 360 : longitudes[index + 1]
    if (next - longitudes[index] > gap) { gap = next - longitudes[index]; start = next % 360 }
  }
  const west = start > 180 ? start - 360 : start
  const latitudes = events.map((event) => Math.max(-85, Math.min(85, event.latitude)))
  return [[west, Math.min(...latitudes)], [west + 360 - gap, Math.max(...latitudes)]]
}
