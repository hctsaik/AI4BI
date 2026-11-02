# Offline geographic assets

`world_50m.json` is copied unchanged from Plotly.js v4.0.0:
https://raw.githubusercontent.com/plotly/plotly.js/v4.0.0/dist/topojson/world_50m.json

- Retrieved: 2026-09-06
- Bytes: 1692310
- SHA-256: `20a160dbd13dd2bfa22f1858c0ae657860ea066d889563c51da383fd9696d759`
- Upstream repository license: `LICENSE.txt`, copied from
  https://raw.githubusercontent.com/plotly/plotly.js/v4.0.0/LICENSE
- Geo rendering API: https://plotly.com/javascript/reference/scattergeo/

Vite copies this directory into the app distribution. The Python static asset
manifest hashes the map, license and this provenance file together with the UI.
Use only the same-origin `/maps/` URL; do not fall back to a public CDN.
This generalized basemap supplies geographic context, not street-level tiles.
