"""Incrementally fetch IMF PortWatch daily AIS data for Cuban ports.

PortWatch's ArcGIS FeatureServer:
    https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/Daily_Ports_Data/FeatureServer/0/query

We aggregate daily port-calls + import/export tonnage to monthly totals,
broadcast across all Cuban provinces (the index is national-level for ports).
"""
from __future__ import annotations

import sys
from datetime import date, timedelta

import pandas as pd
import requests

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from _common import upsert_panel  # noqa: E402
from config import PANEL_PATH, last_complete_month, missing_months  # noqa: E402

# UN/LOCODE values verified to be present in PortWatch's directory (see
# data/raw/portwatch/portwatch_coverage.csv in the parent repo).
CUBA_UNLOCODES = ["CUHAV", "CUMAR", "CUMTZ", "CUCFG", "CUSCU", "CUQNU", "CUMOA"]
ENDPOINT = ("https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/"
            "Daily_Ports_Data/FeatureServer/0/query")


def _query(where: str, offset: int = 0) -> dict:
    params = {
        "where": where,
        "outFields": ("portid,portname,date,portcalls,portcalls_tanker,"
                      "portcalls_container,portcalls_cargo,import,export"),
        "f": "json",
        "resultRecordCount": 2000,
        "resultOffset": offset,
        "orderByFields": "date ASC",
    }
    r = requests.get(ENDPOINT, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def fetch_month(year: int, month: int) -> pd.DataFrame | None:
    start = date(year, month, 1)
    end = (date(year+1, 1, 1) if month == 12 else date(year, month+1, 1))
    # Epoch-ms is the safer ArcGIS filter form; portid IN (...) needs UN/LOCODE-style strings
    quoted = ",".join(f"'{u}'" for u in CUBA_UNLOCODES)
    where = (f"portid IN ({quoted}) AND date >= DATE '{start.isoformat()}' "
             f"AND date < DATE '{end.isoformat()}'")
    rows: list[dict] = []
    offset = 0
    while True:
        try:
            payload = _query(where, offset)
        except Exception as e:  # noqa: BLE001
            print(f"  [{year}-{month:02d}] PortWatch query failed: {e}", flush=True)
            return None
        feats = payload.get("features", [])
        if not feats:
            break
        for f in feats:
            rows.append(f["attributes"])
        if not payload.get("exceededTransferLimit"):
            break
        offset += len(feats)
    return pd.DataFrame(rows) if rows else None


def main() -> None:
    ey, em = last_complete_month(lag_days=10)
    months = missing_months(PANEL_PATH, "port_calls_total", ey, em)
    if not months:
        print(f"[port] panel current through {ey}-{em:02d}; nothing to fetch.")
        return
    print(f"[port] fetching {len(months)} months (through {ey}-{em:02d})")

    # Need province list to broadcast country totals over all rows
    panel = pd.read_csv(PANEL_PATH)
    province_keys = panel[["country", "province_id", "province_name"]].drop_duplicates()
    province_keys = province_keys[province_keys["country"] == "Cuba"]

    new_rows: list[dict] = []
    for (y, m) in months:
        df = fetch_month(y, m)
        if df is None or df.empty:
            print(f"  [{y}-{m:02d}] no PortWatch rows", flush=True)
            continue
        # Convert epoch-ms `date` to YYYY-MM-DD for clarity
        # (we don't keep daily rows; just aggregate to monthly totals)
        agg = {
            "port_calls_total": float(df["portcalls"].fillna(0).sum()),
            "port_tanker_total": float(df["portcalls_tanker"].fillna(0).sum()),
            "port_container_total": float(df["portcalls_container"].fillna(0).sum()),
            "port_cargo_total": float(df["portcalls_cargo"].fillna(0).sum()) if "portcalls_cargo" in df else None,
            "import_mt_total": float(df["import"].fillna(0).sum()),
            "export_mt_total": float(df["export"].fillna(0).sum()),
        }
        for _, prov in province_keys.iterrows():
            new_rows.append({
                "country":       "Cuba",
                "province_id":   prov["province_id"],
                "province_name": prov["province_name"],
                "year":          y, "month": m,
                **agg,
            })
        print(f"  [{y}-{m:02d}] calls={agg['port_calls_total']:.0f} "
              f"imports={agg['import_mt_total']:.0f}mt", flush=True)

    upsert_panel(
        new_rows,
        value_cols=["port_calls_total", "port_tanker_total", "port_container_total",
                    "port_cargo_total", "import_mt_total", "export_mt_total"],
    )


if __name__ == "__main__":
    main()
