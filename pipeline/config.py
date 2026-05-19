"""Configuration shared by every pipeline step.

Authentication
--------------
GEE: a service-account key. In CI, the key is delivered through the
`GEE_SERVICE_ACCOUNT_KEY` environment variable (set as a GitHub Secret
holding the verbatim JSON). Locally, we fall back to the file path used
by the Haiti/Bolivia/Cuba pipelines (`/Users/whl/secrets/haiti-sae-runner.json`).

Date window
-----------
PANEL_START is fixed at 2019-01-01 to keep the historical comparison stable.
`last_complete_month()` returns the most recent month whose satellite
composites should be available — see fetcher docstrings for per-stream latency.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path

import ee  # type: ignore

PANEL_START = "2019-01-01"

# Project / GCP. The Haiti-poverty-monitoring project hosts the shared
# service account used by every "satellite proxy" pipeline in this repo
# family (Haiti, Bolivia, Cuba, Venezuela, Cuba-Monitor).
GEE_PROJECT = "haiti-poverty-monitoring"
GEE_SA_EMAIL = "haiti-sae-runner@haiti-poverty-monitoring.iam.gserviceaccount.com"
GEE_KEY_LOCAL = Path("/Users/whl/secrets/haiti-sae-runner.json")

# Province boundary file (committed to the repo so the pipeline doesn't
# re-download GADM on every run).
REPO_ROOT = Path(__file__).resolve().parents[1]
PROVINCES_PATH = REPO_ROOT / "data" / "cuba_provinces.geojson"
PANEL_PATH = REPO_ROOT / "data" / "panel.csv"
NATIONAL_PATH = REPO_ROOT / "data" / "national_monthly.csv"
# We keep CSV artifacts canonical under /data/, but GitHub Pages only serves
# the /docs/ tree, so the *dashboard.json* (which the SPA fetches) is also
# written into /docs/data/ where the SPA can reach it as ./data/dashboard.json.
DASHBOARD_JSON = REPO_ROOT / "data" / "dashboard.json"
DASHBOARD_JSON_DOCS = REPO_ROOT / "docs" / "data" / "dashboard.json"

# Per-pixel scales (m) used for reduceRegions. These are deliberately
# coarser than each sensor's native resolution to keep request payloads
# under GEE's 10 MB ceiling without sacrificing province-level accuracy.
NO2_SCALE_M = 1000
DNB_SCALE_M = 500
NDVI_SCALE_M = 30
WORLDCOVER_VERSION = "v200"


def init_ee() -> None:
    """Authenticate GEE. Picks the secret first, file second."""
    import socket
    socket.setdefaulttimeout(180.0)  # fail-fast on network blips
    creds_json = os.environ.get("GEE_SERVICE_ACCOUNT_KEY")
    if creds_json:
        creds_dict = json.loads(creds_json)
        credentials = ee.ServiceAccountCredentials(
            creds_dict["client_email"],
            key_data=creds_dict["private_key"],
        )
    elif GEE_KEY_LOCAL.exists():
        credentials = ee.ServiceAccountCredentials(
            GEE_SA_EMAIL, str(GEE_KEY_LOCAL),
        )
    else:
        raise RuntimeError(
            "No GEE credentials found. Set GEE_SERVICE_ACCOUNT_KEY env var "
            f"or place the key at {GEE_KEY_LOCAL}."
        )
    ee.Initialize(credentials=credentials, project=GEE_PROJECT)


def last_complete_month(today: date | None = None, lag_days: int = 15) -> tuple[int, int]:
    """Most recent calendar month whose satellite composites should exist.

    The default 15-day lag covers VIIRS DNB's monthly publication delay
    (~10–15 days after month end). Adjust per stream if needed.
    """
    today = today or date.today()
    # Subtract lag_days, then take the last day of the previous calendar month.
    ref = today
    for _ in range(lag_days):
        ref = ref.fromordinal(ref.toordinal() - 1)
    # First of `ref`'s month minus 1 day = last day of previous complete month
    first_of_ref = date(ref.year, ref.month, 1)
    last_complete = first_of_ref.fromordinal(first_of_ref.toordinal() - 1)
    return last_complete.year, last_complete.month


def month_iter(start_y: int, start_m: int, end_y: int, end_m: int):
    """Yield (year, month) inclusive of both endpoints."""
    y, m = start_y, start_m
    while (y, m) <= (end_y, end_m):
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def missing_months(panel_path: Path, value_col: str, end_y: int, end_m: int) -> list[tuple[int, int]]:
    """List (year, month) pairs the panel does NOT yet have data for under
    `value_col`. Reads the panel CSV; returns [] if every month in the
    window is populated for every province."""
    import pandas as pd
    if not panel_path.exists():
        return list(month_iter(2019, 1, end_y, end_m))
    df = pd.read_csv(panel_path)
    if value_col not in df.columns:
        return list(month_iter(2019, 1, end_y, end_m))
    # A month is "missing" if any province has a NaN for that month.
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["month"] = pd.to_numeric(df["month"], errors="coerce").astype("Int64")
    g = df.groupby(["year", "month"])[value_col].apply(lambda s: int(s.notna().sum()))
    n_provinces = df["province_id"].nunique()
    full = set(k for k, v in g.items() if v >= n_provinces)
    return [(y, m) for (y, m) in month_iter(2019, 1, end_y, end_m) if (y, m) not in full]
