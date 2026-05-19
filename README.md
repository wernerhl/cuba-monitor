# Cuba Concordance Monitor

A self-updating dashboard at **<https://wernerhl.github.io/cuba-monitor>** that
fuses four satellite/economic data streams into a single monthly
**concordance index** for Cuba, 2019m1 → present.

| Stream | Source | Latency |
|---|---|---|
| Tropospheric NO₂ | Sentinel-5P TROPOMI OFFL (GEE) | ~5 days |
| Nighttime lights | NOAA VIIRS DNB monthly composite (GEE) | ~10–15 days |
| Cropland NDVI | Sentinel-2 SR-Harmonized + ESA WorldCover (GEE) | ~5 days |
| Maritime traffic | IMF PortWatch ArcGIS API (7 Cuban ports) | ~weekly |
| Informal FX | cambiocuba.money mirror of El Toque TRMI (USD) | daily |

The index is the **first principal component** of the four
deseasonalized national series, oriented so DNB loads positively and
rescaled so that 2019 mean = 100, 2019 std → ±10 index units per σ.

## Architecture

```
cuba-monitor/
├── .github/workflows/update_data.yml   # monthly cron + manual dispatch
├── pipeline/                           # Python, runs in GitHub Actions
│   ├── config.py                       # auth, paths, window helpers
│   ├── _common.py                      # ee_retry, panel upsert
│   ├── fetch_no2.py
│   ├── fetch_dnb.py
│   ├── fetch_ndvi.py
│   ├── fetch_portwatch.py
│   ├── fetch_eltoque.py
│   ├── build_index.py                  # PCA → national_monthly.csv
│   ├── export_dashboard_data.py        # → dashboard.json
│   └── requirements.txt
├── data/                               # committed; updated by workflow
│   ├── cuba_provinces.geojson          # GADM 4.1 boundaries (static)
│   ├── panel.csv                       # province-month panel (long)
│   ├── national_monthly.csv            # national aggregates + index
│   └── dashboard.json                  # ←─ what the SPA reads
└── docs/                               # GitHub Pages root
    ├── index.html
    ├── style.css
    └── app.js
```

Each fetcher is **idempotent and incremental**: it reads `panel.csv`,
finds the months a stream is missing data for, and only extracts those.
First-time setup populates the full 2019–present window; subsequent
monthly runs add ~1 month per stream.

## Reproducing locally

```bash
git clone https://github.com/wernerhl/cuba-monitor.git
cd cuba-monitor
pip install -r pipeline/requirements.txt

# GEE: drop the service-account key at the local path config.py expects,
# or set GEE_SERVICE_ACCOUNT_KEY=$(cat /path/to/key.json) in the shell.
export GEE_SERVICE_ACCOUNT_KEY="$(cat /path/to/haiti-sae-runner.json)"

cd pipeline
python fetch_portwatch.py    # fastest; no GEE
python fetch_no2.py
python fetch_dnb.py
python fetch_ndvi.py
python fetch_eltoque.py
python export_dashboard_data.py    # → ../data/dashboard.json
```

Open `docs/index.html` via any static server (e.g.
`python -m http.server` from the repo root, then visit
`http://localhost:8000/docs/`).

## CI

The workflow at `.github/workflows/update_data.yml` runs at **06:00 UTC
on the 15th of each month**. By that date all satellite composites for
the previous month are published. Per-fetcher steps use
`continue-on-error: true` so one flaky source doesn't block the others —
the build_index step always runs and republishes whatever is current.

## Methodology

`build_index.py` aggregates the panel to monthly national series:

* **NO₂**: mean tropospheric column density across all 16 provinces
* **DNB**: log of summed total luminosity (sum-of-lights × pixel area)
* **NDVI**: mean cropland-masked NDVI across all provinces
* **Ports**: log of total monthly port-calls across 7 Cuban ports

Each is deseasonalized by month-of-year demeaning. PCA on the
standardized residuals; PC1 is the concordance index. Diagnostics
(eigenvalue ratio λ₁/λ₂, PC1 explained variance, loadings) are exported
in `dashboard.json` and shown in the dashboard.

## Notes

* The 16-polygon Cuba boundaries use GADM 4.1, with the pre-2011 Havana
  labels remapped to the modern Artemisa / La Habana scheme (see the
  parent paper for details).
* Eltoque/cambiocuba.money is the most fragile source. Failures are
  swallowed; the FX panel will simply gap.
* The PCA index is recomputed on every run, so old observations may
  shift slightly as the loadings re-fit.

## Citation

Hernani-Limarino, W. L. (2026). *Monitoring in the Dark: A Satellite
Concordance Index for Economies Without Statistics*. Working paper.

## License

MIT (see `LICENSE`).
