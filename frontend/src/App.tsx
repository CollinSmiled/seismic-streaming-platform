import './App.css'

function App() {
  return (
    <main className="app">
      <header className="app-header">
        <h1>Seismic Streaming Platform</h1>
      </header>

      <section aria-labelledby="setup-heading">
        <h2 id="setup-heading">Project setup</h2>
        <p>
          The map and event feed will appear here as the pipeline is built.
        </p>
        <p>
          Earthquake data source:{' '}
          <a href="https://www.seismicportal.eu/">EMSC-CSEM SeismicPortal</a>
        </p>
      </section>
    </main>
  )
}

export default App
