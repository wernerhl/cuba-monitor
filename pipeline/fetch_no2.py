"""Incrementally fetch TROPOMI tropospheric NO₂ per Cuban province.

Latency: OFFL composite typically lands ~5 days after acquisition; NRTI
within 24 h. We default to OFFL with NRTI fallback for the trailing month.
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import ee  # type: ignore

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from _common import ee_retry, load_provinces_fc, month_bounds, upsert_panel  # noqa: E402
from config import NO2_SCALE_M, init_ee, last_complete_month, missing_months, PANEL_PATH  # noqa: E402

OFFL = "COPERNICUS/S5P/OFFL/L3_NO2"
NRTI = "COPERNICUS/S5P/NRTI/L3_NO2"
NO2_BAND = "tropospheric_NO2_column_number_density"
CLOUD_BAND = "cloud_fraction"
CLOUD_MAX = 0.5
N_WORKERS = 6


def pick_collection(start: str, end: str) -> tuple[str, int] | None:
    for cname in (OFFL, NRTI):
        n = ee_retry(
            lambda c=cname: ee.ImageCollection(c).filterDate(start, end).size().getInfo(),
            tag=f"pick {cname} {start}",
        )
        if n and n > 0:
            return cname, int(n)
    return None


def composite(cname: str, start: str, end: str, geom: ee.Geometry) -> ee.Image:
    coll = (ee.ImageCollection(cname)
            .filterDate(start, end)
            .filterBounds(geom))

    def _mask(img):
        return img.select(NO2_BAND).updateMask(img.select(CLOUD_BAND).lte(CLOUD_MAX))

    no2 = coll.map(_mask).mean().rename("no2")
    cloud = coll.select(CLOUD_BAND).mean().rename("cloud_fraction")
    return no2.addBands(cloud)


def reduce_one(cname: str, start: str, end: str, props: dict, geom: ee.Geometry) -> dict:
    img = composite(cname, start, end, geom)
    reducer = ee.Reducer.mean().combine(ee.Reducer.count(), sharedInputs=True)
    out = ee_retry(
        lambda: img.reduceRegion(
            reducer=reducer, geometry=geom, scale=NO2_SCALE_M,
            tileScale=4, maxPixels=int(1e10), bestEffort=True,
        ).getInfo(),
        tag=f"no2 {props.get('province_id')} {start}",
    )
    return {**props, **out}


def main() -> None:
    init_ee()
    gdf, _ = load_provinces_fc()
    ey, em = last_complete_month()
    months = missing_months(PANEL_PATH, "no2_mean", ey, em)
    if not months:
        print(f"[no2] panel current through {ey}-{em:02d}; nothing to fetch.")
        return
    print(f"[no2] fetching {len(months)} months (through {ey}-{em:02d})")

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
        picked = pick_collection(start, end)
        if picked is None:
            print(f"  [{y}-{m:02d}] no scenes")
            continue
        cname, n_img = picked

        def _work(prov):
            props = {k: prov[k] for k in ("country", "province_id", "province_name")}
            try:
                return reduce_one(cname, start, end, props, prov["geom"])
            except Exception as e:  # noqa: BLE001
                return {**props, "_err": str(e)}

        with ThreadPoolExecutor(max_workers=N_WORKERS) as ex:
            for fut in as_completed([ex.submit(_work, p) for p in provinces]):
                out = fut.result()
                if out.get("_err"):
                    continue
                new_rows.append({
                    "country":             out.get("country"),
                    "province_id":         out.get("province_id"),
                    "province_name":       out.get("province_name"),
                    "year":                y,
                    "month":                m,
                    "no2_mean":            out.get("no2_mean"),
                    "no2_n_pixels":        out.get("no2_count"),
                    "no2_cloud_fraction":  out.get("cloud_fraction_mean"),
                    "no2_source":          "OFFL" if cname == OFFL else "NRTI",
                    "no2_n_scenes":        n_img,
                })
        print(f"  [{y}-{m:02d}] {cname.split('/')[-2]} {n_img} scenes -> "
              f"{sum(1 for r in new_rows if r['year']==y and r['month']==m)} provinces",
              flush=True)

    upsert_panel(
        new_rows,
        value_cols=["no2_mean", "no2_n_pixels", "no2_cloud_fraction",
                    "no2_source", "no2_n_scenes"],
    )


if __name__ == "__main__":
    main()
