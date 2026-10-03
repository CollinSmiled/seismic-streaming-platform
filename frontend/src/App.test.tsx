import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import App from './App'

afterEach(cleanup)

describe('App', () => {
  it('credits the upstream earthquake data source', () => {
    render(<App />)

    expect(
      screen.getByRole('link', { name: 'EMSC-CSEM SeismicPortal' }).getAttribute('href'),
    ).toBe('https://www.seismicportal.eu/')
  })
})
