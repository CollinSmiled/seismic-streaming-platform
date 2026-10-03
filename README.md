# Seismic Streaming Platform

A real-time earthquake event platform that will ingest EMSC notifications through Kafka, store processed events in PostgreSQL, and display them on a React and Mapbox map. Prometheus and Grafana will monitor the pipeline.

## Status

Initial repository setup. The ingestion service, processor, API, frontend, and deployment files will be added in subsequent milestones.

## Data source

Earthquake data will come from [EMSC-CSEM SeismicPortal](https://www.seismicportal.eu/). EMSC data has its own [CC BY 4.0 attribution terms](https://www.seismicportal.eu/terms.html).

## Copyright

All rights reserved. No license is granted for this repository's original code.
