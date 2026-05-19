"""Helpers shared across the per-stream fetchers."""
from __future__ import annotations

import time
from pathlib import Path

import ee  # type: ignore
import geopandas as gpd
import pandas as pd

from config import PANEL_PATH, PROVINCES_PATH


def load_provinces_fc() -> tuple[gpd.GeoDataFrame, ee.FeatureCollection]:
    gdf = gpd.read_file(PROVINCES_PATH).to_crs("EPSG:4326")
    feats = []
    for _, row in gdf.iterrows():
        geom = ee.Geometry(row.geometry.__geo_interface__)
        feats.append(ee.Feature(geom, {
            "country":       row.get("country", "Cuba"),
            "province_id":   row["province_id"],
            "province_name": row["province_name"],
        }))
    return gdf, ee.FeatureCollection(feats)


def month_bounds(year: int, month: int) -> tuple[str, str]:
    if month == 12:
        return f"{year:04d}-12-01", f"{year+1:04d}-01-01"
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month+1:02d}-01"


def ee_retry(fn, *, tries: int = 6, base_delay: float = 2.0, tag: str = ""):
    """Exponential backoff for transient GEE/network failures (429/5xx/timeout)."""
    import random
    delay = base_delay
    for attempt in range(1, tries + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            ml = msg.lower()
            transient = (
                "429" in msg or "Too Many Requests" in msg or "rate" in ml
                or "500 " in msg or "503" in msg
                or "internal error" in ml or "deadline" in ml
                or "timed out" in ml or "timeout" in ml
                or "connection reset" in ml or "connection aborted" in ml
                or "remote disconnected" in ml or "remote end closed" in ml
                or "ssleof" in ml or "ssl" in ml
            )
            if not transient or attempt == tries:
                raise
            jitter = random.uniform(0, delay * 0.4)
            sleep_for = delay + jitter
            if tag:
                print(f"    [retry {attempt}/{tries}] {tag}: {msg[:80]} → sleep {sleep_for:.1f}s",
                      flush=True)
            time.sleep(sleep_for)
            delay = min(delay * 2, 64.0)


def upsert_panel(rows: list[dict], value_cols: list[str]) -> None:
    """Merge new rows into the persistent panel CSV. Re-running is safe
    — existing values for the same (province_id, year, month) are
    overwritten by the new rows."""
    if not rows:
        return
    new_df = pd.DataFrame(rows)
    # Ensure the date column exists; some fetchers fill it in, others don't.
    if "date" not in new_df.columns:
        new_df["date"] = pd.to_datetime(
            new_df["year"].astype(str) + "-" + new_df["month"].astype(str).str.zfill(2) + "-01"
        )
    new_df["year"] = pd.to_numeric(new_df["year"], errors="coerce").astype("Int64")
    new_df["month"] = pd.to_numeric(new_df["month"], errors="coerce").astype("Int64")

    if PANEL_PATH.exists():
        old = pd.read_csv(PANEL_PATH)
        old["year"] = pd.to_numeric(old["year"], errors="coerce").astype("Int64")
        old["month"] = pd.to_numeric(old["month"], errors="coerce").astype("Int64")
        # Drop the rows we're about to replace
        key = ["province_id", "year", "month"]
        merge_keys = pd.MultiIndex.from_frame(new_df[key])
        mask = ~pd.MultiIndex.from_frame(old[key]).isin(merge_keys)
        old = old[mask]
        # Add any missing columns
        for col in value_cols:
            if col not in old.columns:
                old[col] = pd.NA
        combined = pd.concat([old, new_df], ignore_index=True, sort=False)
    else:
        combined = new_df

    combined = combined.sort_values(["province_id", "year", "month"]).reset_index(drop=True)
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(PANEL_PATH, index=False)
    print(f"  [panel] wrote {len(combined)} rows; {len(new_df)} new/updated; cols added: {value_cols}",
          flush=True)
