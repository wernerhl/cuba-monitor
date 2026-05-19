"""Incrementally fetch the informal CUP/USD rate from cambiocuba.money.

cambiocuba.money exposes a single bulk-history endpoint that returns the
full daily series for one currency at a time as an XLSX. We use the
USD sheet's daily median ("Mediana") as the headline informal rate.

The endpoint is reasonably stable but may change format; this fetcher is
the most fragile part of the pipeline. Failures are non-fatal upstream
(see continue-on-error in the workflow).
"""
from __future__ import annotations

import io
import sys
from datetime import date

import pandas as pd
import requests

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from _common import upsert_panel  # noqa: E402
from config import PANEL_PATH, last_complete_month, missing_months  # noqa: E402

ENDPOINT = "https://api.cambiocuba.money/api/v1/download-excel/all-days-stats"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (cuba-monitor pipeline; "
                   "https://github.com/wernerhl/cuba-monitor)"),
}


def fetch_full_series() -> pd.DataFrame:
    r = requests.get(ENDPOINT, params={"x_cur": "USD"}, headers=HEADERS, timeout=120)
    r.raise_for_status()
    xl = pd.ExcelFile(io.BytesIO(r.content))
    # The workbook has one sheet per currency; pick the USD sheet defensively
    target = next((s for s in xl.sheet_names if "USD" in s.upper()), xl.sheet_names[0])
    df = xl.parse(target)
    # Standardize the median column name we saw across vintages
    rename = {}
    for c in df.columns:
        cl = str(c).lower()
        if cl in ("fecha", "date", "día", "dia"):
            rename[c] = "date"
        elif cl in ("mediana", "median"):
            rename[c] = "median"
    df = df.rename(columns=rename)
    if "date" not in df.columns or "median" not in df.columns:
        raise RuntimeError(
            f"cambiocuba.money workbook columns changed: got {list(df.columns)}"
        )
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "median"])
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month
    return df[["date", "year", "month", "median"]]


def main() -> None:
    ey, em = last_complete_month(lag_days=3)
    months = missing_months(PANEL_PATH, "fx_cup_per_usd_informal", ey, em)
    if not months:
        print(f"[fx] panel current through {ey}-{em:02d}; nothing to fetch.")
        return

    print(f"[fx] fetching full cambiocuba.money history "
          f"(panel needs {len(months)} months through {ey}-{em:02d})")
    daily = fetch_full_series()
    monthly = (daily.groupby(["year", "month"])["median"]
                    .mean().reset_index()
                    .rename(columns={"median": "fx_cup_per_usd_informal"}))

    # Broadcast monthly FX across all Cuban provinces (FX is national)
    panel = pd.read_csv(PANEL_PATH)
    provinces = panel[panel["country"] == "Cuba"][[
        "country", "province_id", "province_name"
    ]].drop_duplicates()

    new_rows: list[dict] = []
    want = set(months)
    for _, row in monthly.iterrows():
        if (int(row["year"]), int(row["month"])) not in want:
            continue
        for _, prov in provinces.iterrows():
            new_rows.append({
                "country":       "Cuba",
                "province_id":   prov["province_id"],
                "province_name": prov["province_name"],
                "year":          int(row["year"]),
                "month":         int(row["month"]),
                "fx_cup_per_usd_informal": float(row["fx_cup_per_usd_informal"]),
            })
    print(f"  matched {len({(r['year'], r['month']) for r in new_rows})} months × "
          f"{len(provinces)} provinces", flush=True)

    upsert_panel(new_rows, value_cols=["fx_cup_per_usd_informal"])


if __name__ == "__main__":
    main()
