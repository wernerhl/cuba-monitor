"""Compute the PCA-based national concordance index from the panel.

Workflow:
  1. Aggregate the province-month panel to national-month time series
  2. Deseasonalize each stream (month-specific demeaning)
  3. Standardize and run PCA on (NO₂, DNB, NDVI, Ports)
  4. Orient PC1 so that higher = brighter = more activity (sign-flip
     if DNB loading is negative)
  5. Rescale so 2019 mean = 100, 2019 std → +/-10 per σ

Outputs:
  data/national_monthly.csv  — national-aggregate streams + index
  data/dashboard.json        — exported by export_dashboard_data.py

The eigenvalue ratio λ₁/λ₂ is reported as a "concordance" diagnostic; ≥ 2
is a strong signal that PC1 captures a single common component.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from config import NATIONAL_PATH, PANEL_PATH  # noqa: E402

STREAMS = ["no2", "dnb", "ndvi", "ports"]


def aggregate_national(df: pd.DataFrame) -> pd.DataFrame:
    """National monthly means/counts in RAW units, matching paper §7.1
    and Table 3 (DNB mean radiance in nW/cm²/sr, ports as raw count).
    Log-transforming DNB/Ports flips three loading signs vs. the paper."""
    nat = df.groupby(["year", "month"]).agg(
        no2=("no2_mean", "mean"),
        dnb=("dnb_mean", "mean"),
        ndvi=("ndvi_cropland", "mean"),
        ports=("port_calls_total", "first"),
        fx=("fx_cup_per_usd_informal", "first"),
        thermal_ops=("thermal_n_plants_operational", "mean"),
        import_mt=("import_mt_total", "first"),
    ).reset_index().sort_values(["year", "month"])
    nat["date"] = pd.to_datetime(
        nat["year"].astype(str) + "-" + nat["month"].astype(str).str.zfill(2) + "-01"
    )
    return nat


def deseasonalize(nat: pd.DataFrame) -> pd.DataFrame:
    for col in STREAMS:
        monthly_means = nat.groupby("month")[col].transform("mean")
        nat[f"{col}_ds"] = nat[col] - monthly_means
    return nat


def fit_pca_index(nat: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    cols = [f"{c}_ds" for c in STREAMS]
    sub = nat.dropna(subset=cols).copy()
    if len(sub) < 12:
        raise RuntimeError(f"Not enough complete months for PCA: {len(sub)}")
    X = StandardScaler().fit_transform(sub[cols].values)
    pca = PCA(n_components=len(cols))
    scores = pca.fit_transform(X)
    pc1 = scores[:, 0]
    # Orient PC1 so DNB loads positively (paper §7.1).
    dnb_loading = pca.components_[0][STREAMS.index("dnb")]
    flip = dnb_loading < 0
    if flip:
        pc1 = -pc1
        loadings_pc1 = -pca.components_[0]
    else:
        loadings_pc1 = pca.components_[0]
    sub["concordance_idx_raw"] = pc1
    nat = nat.merge(
        sub[["year", "month", "concordance_idx_raw"]],
        on=["year", "month"], how="left",
    )

    # Rescale: 2019 mean = 100, 2019 std → 10 index units per σ
    base = nat.loc[nat["year"] == 2019, "concordance_idx_raw"].mean()
    std = nat.loc[nat["year"] == 2019, "concordance_idx_raw"].std()
    nat["concordance_100"] = 100 + (nat["concordance_idx_raw"] - base) / std * 10

    diagnostics = {
        "n_months_pca_fit": int(len(sub)),
        "pc1_share":        round(float(pca.explained_variance_ratio_[0]) * 100, 1),
        "pc2_share":        round(float(pca.explained_variance_ratio_[1]) * 100, 1),
        "eigenvalue_ratio": round(float(pca.explained_variance_[0] /
                                        pca.explained_variance_[1]), 2),
        "loadings": {
            "NO₂":   round(float(loadings_pc1[0]), 3),
            "DNB":   round(float(loadings_pc1[1]), 3),
            "NDVI":  round(float(loadings_pc1[2]), 3),
            "Ports": round(float(loadings_pc1[3]), 3),
        },
    }
    return nat, diagnostics


def main() -> dict:
    df = pd.read_csv(PANEL_PATH)
    print(f"[index] panel rows={len(df)}; provinces={df['province_id'].nunique()}")
    nat = aggregate_national(df)
    nat = deseasonalize(nat)
    nat, diag = fit_pca_index(nat)

    NATIONAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    nat.to_csv(NATIONAL_PATH, index=False)
    print(f"[index] wrote {NATIONAL_PATH.name} ({len(nat)} rows)")
    print(f"  PC1 share: {diag['pc1_share']}%  ratio λ₁/λ₂: {diag['eigenvalue_ratio']}")
    print(f"  loadings: {diag['loadings']}")
    return diag


if __name__ == "__main__":
    diag = main()
    print(json.dumps(diag, indent=2, ensure_ascii=False))
