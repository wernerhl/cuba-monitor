"""Incrementally fetch VIIRS DNB monthly nightlights per Cuban province.

Source: NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG (stray-light-corrected). Each
calendar month is a single image; latency ~10-15 days after month end.
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import ee  # type: ignore

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from _common import ee_retry, load_provinces_fc, month_bounds, upsert_panel  # noqa: E402
from config import DNB_SCALE_M, init_ee, last_complete_month, missing_months, PANEL_PATH  # noqa: E402

COLLECTION = "NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG"
BAND = "avg_rad"
N_WORKERS = 6
PIXEL_AREA_M2 = DNB_SCALE_M * DNB_SCALE_M


def monthly_image(start: str, end: str) -> "ee.Image | None":
    coll = ee.ImageCollection(COLLECTION).select(BAND).filterDate(start, end)
    n = ee_retry(lambda: coll.size().getInfo(), tag=f"dnb size {start}")
    return ee.Image(coll.first()) if n else None


def reduce_one(img: ee.Image, props: dict, geom: ee.Geometry) -> dict:
    reducer = (
        ee.Reducer.mean()
        .combine(ee.Reducer.sum(), sharedInputs=True)
        .combine(ee.Reducer.count(), sharedInputs=True)
    )
    out = ee_retry(
        lambda: img.reduceRegion(
            reducer=reducer, geometry=geom, scale=DNB_SCALE_M,
            maxPixels=int(1e10), bestEffort=True, tileScale=4,
        ).getInfo(),
        tag=f"dnb {props.get('province_id')} {props.get('_ym')}",
    )
    return {**props, **out}


def main() -> None:
    init_ee()
    gdf, _ = load_provinces_fc()
    ey, em = last_complete_month()
    months = missing_months(PANEL_PATH, "dnb_mean", ey, em)
    if not months:
        print(f"[dnb] panel current through {ey}-{em:02d}; nothing to fetch.")
        return
    print(f"[dnb] fetching {len(months)} months (through {ey}-{em:02d})")

    provinces = []
    for _, row in gdf.iterrows():
        provinces.append({
            "country":       row.get("country", "Cuba"),
            "province_id":   row["province_id"],
            "province_name": row["province_name"],
            "geom":          ee.Geometry(row.geometry.__geo_interface__),
        })

    new_rows: list[dict] = []
    for (y, m) in months:
        start, end = month_bounds(y, m)
        img = monthly_image(start, end)
        if img is None:
            print(f"  [{y}-{m:02d}] no VCMSLCFG image yet")
            continue

        def _work(p):
            props = {k: p[k] for k in ("country", "province_id", "province_name")}
            props["_ym"] = f"{y}-{m:02d}"
            try:
                return reduce_one(img, props, p["geom"])
            except Exception as e:  # noqa: BLE001
                return {**props, "_err": str(e)}

        n_ok = 0
        with ThreadPoolExecutor(max_workers=N_WORKERS) as ex:
            for fut in as_completed([ex.submit(_work, p) for p in provinces]):
                out = fut.result()
                if out.get("_err"):
                    continue
                mean = out.get(f"{BAND}_mean")
                ssum = out.get(f"{BAND}_sum")
                new_rows.append({
                    "country":         out["country"],
                    "province_id":     out["province_id"],
                    "province_name":   out["province_name"],
                    "year":            y, "month": m,
                    "dnb_mean":        mean,
                    "dnb_total_lum":   (ssum * PIXEL_AREA_M2) if ssum is not None else None,
                    "dnb_n_pixels":    out.get(f"{BAND}_count"),
                })
                if mean is not None:
                    n_ok += 1
        print(f"  [{y}-{m:02d}] {n_ok}/{len(provinces)} provinces", flush=True)

    upsert_panel(
        new_rows,
        value_cols=["dnb_mean", "dnb_total_lum", "dnb_n_pixels"],
    )


if __name__ == "__main__":
    main()
