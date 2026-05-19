"""Incrementally fetch Sentinel-2 NDVI per Cuban province, cropland-masked.

Cropland = ESA WorldCover v200 classes 40 (cropland) + 30 (grassland).
"""
from __future__ import annotations

import sys

import ee  # type: ignore

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from _common import ee_retry, load_provinces_fc, month_bounds, upsert_panel  # noqa: E402
from config import NDVI_SCALE_M, init_ee, last_complete_month, missing_months, PANEL_PATH, WORLDCOVER_VERSION  # noqa: E402

CLOUD_PCT_MAX = 30
SIMPLIFY_DEG = 0.001


def cropland_mask() -> ee.Image:
    wc = ee.ImageCollection(f"ESA/WorldCover/{WORLDCOVER_VERSION}").first()
    return wc.eq(40).Or(wc.eq(30))


def s2_ndvi_composite(start: str, end: str, region: ee.Geometry, cropland: ee.Image) -> ee.Image:
    coll = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterDate(start, end)
            .filterBounds(region)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", CLOUD_PCT_MAX)))

    def mask_clouds(img):
        scl = img.select("SCL")
        bad = scl.eq(3).Or(scl.eq(8)).Or(scl.eq(9)).Or(scl.eq(10))
        return img.updateMask(bad.Not())

    masked = coll.map(mask_clouds)
    ndvi = masked.map(lambda img: img.normalizedDifference(["B8", "B4"]).rename("ndvi"))
    return ndvi.median().updateMask(cropland).rename("ndvi")


def main() -> None:
    init_ee()
    gdf, fc = load_provinces_fc()
    ey, em = last_complete_month()
    months = missing_months(PANEL_PATH, "ndvi_cropland", ey, em)
    if not months:
        print(f"[ndvi] panel current through {ey}-{em:02d}; nothing to fetch.")
        return
    print(f"[ndvi] fetching {len(months)} months (through {ey}-{em:02d})")

    cropland = cropland_mask()
    region = fc.geometry().bounds()
    reducer = ee.Reducer.mean().combine(ee.Reducer.count(), sharedInputs=True)

    new_rows: list[dict] = []
    for (y, m) in months:
        start, end = month_bounds(y, m)
        try:
            img = s2_ndvi_composite(start, end, region, cropland)
            stats = ee_retry(
                lambda: img.reduceRegions(
                    collection=fc, reducer=reducer,
                    scale=NDVI_SCALE_M, tileScale=4,
                ).getInfo(),
                tag=f"ndvi {y}-{m:02d}",
            )
        except Exception as e:  # noqa: BLE001
            print(f"  [{y}-{m:02d}] error: {e}", flush=True)
            continue
        n_with = 0
        for feat in stats["features"]:
            p = feat["properties"]
            mean = p.get("mean")
            n = int(p.get("count") or 0)
            new_rows.append({
                "country":          p.get("country"),
                "province_id":      p.get("province_id"),
                "province_name":    p.get("province_name"),
                "year":             y, "month": m,
                "ndvi_cropland":    mean,
                "ndvi_n_pixels":    n,
            })
            if mean is not None and n > 0:
                n_with += 1
        print(f"  [{y}-{m:02d}] {n_with}/{len(stats['features'])} provinces", flush=True)

    upsert_panel(
        new_rows,
        value_cols=["ndvi_cropland", "ndvi_n_pixels"],
    )


if __name__ == "__main__":
    main()
