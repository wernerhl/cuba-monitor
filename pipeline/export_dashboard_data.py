"""Produce data/dashboard.json — the single file the frontend SPA reads.

Combines national time series, PCA diagnostics, the latest subnational DNB
snapshot, and a curated events timeline. Kept compact (~30-40 KB) so the
SPA loads instantly.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_index import main as build_index_main  # noqa: E402
from config import DASHBOARD_JSON, NATIONAL_PATH, PANEL_PATH  # noqa: E402


# Curated key events to mark on the time series
EVENTS = [
    {"date": "2020-03", "label": "COVID-19",                 "type": "crisis"},
    {"date": "2021-01", "label": "Tarea Ordenamiento",       "type": "policy"},
    {"date": "2022-08", "label": "Matanzas oil-tank fire",   "type": "crisis"},
    {"date": "2023-01", "label": "US CHNV parole launches",  "type": "policy"},
    {"date": "2024-10", "label": "Nationwide grid collapse", "type": "crisis"},
    {"date": "2025-01", "label": "US enforcement reset",     "type": "policy"},
    {"date": "2026-01", "label": "Oil-supply cutoff",        "type": "crisis"},
]


def _round(x, n=4):
    """Round to `n` decimals OR significant figures for very small values."""
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return None
    f = float(x)
    if f == 0:
        return 0.0
    # For numbers smaller than 10^-n, fall back to 4 significant figures
    if abs(f) < 10 ** -n:
        from math import floor, log10
        sf = 4
        digits = sf - int(floor(log10(abs(f)))) - 1
        return round(f, digits)
    return round(f, n)


def latest_subnational_dnb(panel: pd.DataFrame) -> list[dict]:
    """Most recent month with DNB data, per province, plus YoY change."""
    cu = panel[panel["country"] == "Cuba"].copy()
    cu = cu.dropna(subset=["dnb_mean"])
    if cu.empty:
        return []
    cu["ymd"] = cu["year"] * 12 + cu["month"]
    latest_ymd = cu["ymd"].max()
    latest_y, latest_m = (latest_ymd - 1) // 12, ((latest_ymd - 1) % 12) + 1
    cur = cu[cu["ymd"] == latest_ymd]
    prev_ymd = latest_ymd - 12
    prev = cu[cu["ymd"] == prev_ymd][["province_id", "dnb_mean"]].rename(
        columns={"dnb_mean": "dnb_yoy_prev"}
    )
    snap = cur.merge(prev, on="province_id", how="left")
    snap["dnb_yoy_pct"] = (snap["dnb_mean"] / snap["dnb_yoy_prev"] - 1) * 100
    return [
        {
            "province_id":   r["province_id"],
            "province_name": r["province_name"],
            "dnb_mean":      _round(r["dnb_mean"], 3),
            "dnb_yoy_pct":   _round(r["dnb_yoy_pct"], 1),
        }
        for _, r in snap.sort_values("dnb_mean", ascending=False).iterrows()
    ]


def main() -> None:
    # Refresh national_monthly.csv + collect diagnostics
    diag = build_index_main()
    nat = pd.read_csv(NATIONAL_PATH)
    panel = pd.read_csv(PANEL_PATH)

    # Normalize component streams to 2019 = 100 for the secondary panel
    base_year = nat[nat["year"] == 2019]
    for col in ("no2", "dnb", "ndvi", "ports"):
        baseline = base_year[col].mean()
        if baseline and not np.isnan(baseline):
            nat[f"{col}_100"] = nat[col] / baseline * 100

    monthly = []
    for _, r in nat.iterrows():
        monthly.append({
            "date":   f"{int(r['year']):04d}-{int(r['month']):02d}-01",
            "year":   int(r["year"]),
            "month":  int(r["month"]),
            "no2":    _round(r.get("no2")),
            "dnb":    _round(r.get("dnb")),
            "ndvi":   _round(r.get("ndvi")),
            "ports":  _round(r.get("ports")),
            "fx":     _round(r.get("fx")),
            "thermal_ops": _round(r.get("thermal_ops")),
            "import_mt":   _round(r.get("import_mt")),
            "no2_100":     _round(r.get("no2_100")),
            "dnb_100":     _round(r.get("dnb_100")),
            "ndvi_100":    _round(r.get("ndvi_100")),
            "ports_100":   _round(r.get("ports_100")),
            "concordance":     _round(r.get("concordance_idx_raw")),
            "concordance_100": _round(r.get("concordance_100")),
        })

    out = {
        "last_updated":  datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "panel_window":  {"start": "2019-01-01",
                          "end": f"{int(nat['year'].max()):04d}-{int(nat.loc[nat['year'] == nat['year'].max(), 'month'].max()):02d}-01"},
        "n_provinces":   int(panel["province_id"].nunique()),
        "diagnostics":   diag,
        "events":        EVENTS,
        "monthly":       monthly,
        "subnational_dnb_latest": latest_subnational_dnb(panel),
        "methodology": {
            "streams": ["TROPOMI NO₂", "VIIRS DNB total luminosity",
                        "Sentinel-2 NDVI (cropland)", "IMF PortWatch port calls"],
            "deseasonalization": "Month-specific demeaning",
            "extraction":        "PCA, first principal component (oriented so DNB loads positively)",
            "rescaling":         "2019 mean → 100, 2019 std → 10 index units per σ",
            "paper":             "Hernani-Limarino (2026), 'Monitoring in the Dark: A Satellite Concordance Index for Economies Without Statistics'",
            "code":              "https://github.com/wernerhl/cuba-monitor",
        },
    }
    DASHBOARD_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(DASHBOARD_JSON, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f"[dashboard] wrote {DASHBOARD_JSON.name} "
          f"({DASHBOARD_JSON.stat().st_size/1024:.1f} KB)")
    print(f"  last month: {out['panel_window']['end']}")
    print(f"  PC1 share: {diag['pc1_share']}%  eigenvalue ratio: {diag['eigenvalue_ratio']}")


if __name__ == "__main__":
    main()
