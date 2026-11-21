"""Simulate a 50,000-session e-commerce A/B test with built-in flaws.

The experiment is intentionally flawed so the audit has something real to
catch:

  * Sample Ratio Mismatch: the intended 50/50 split actually delivered
    25,400 control / 24,600 variant (50.8% / 49.2%).
  * A small conversion uplift (+0.3pp) that is not statistically
    significant at the achieved sample size.
  * A revenue mean pulled up by a handful of whale orders, so a
    parametric test looks borderline significant while a rank test does
    not — the mean difference is outlier-driven, not a real shift.

Seeded for reproducibility. Run: python generate_data.py

Columns: user_id, date, variant, device, converted, revenue
"""

import numpy as np
import pandas as pd

SEED = 14
N = 50_000
N_CONTROL = 25_400  # 50.8% — the SRM (intended split was 50/50)
N_VARIANT = N - N_CONTROL

# Conversion rates by (variant, device). Control blends to 10.0% overall,
# variant to 10.3% overall; the uplift is split across both devices.
CONVERSION = {
    ("control", "mobile"): 0.090,
    ("control", "desktop"): 0.115,
    ("variant", "mobile"): 0.093,
    ("variant", "desktop"): 0.118,
}

SPEND_MU, SPEND_SIGMA = 4.7, 0.6  # lognormal spend for converted users
N_WHALES = 6
WHALE_AMOUNTS = [1500.0, 1800.0, 2200.0, 1900.0, 2600.0, 2100.0]


def main() -> None:
    rng = np.random.default_rng(SEED)

    variant = np.array(["control"] * N_CONTROL + ["variant"] * N_VARIANT)
    rng.shuffle(variant)

    device = np.where(rng.random(N) < 0.60, "mobile", "desktop")

    dates = pd.date_range("2026-11-03", periods=14, freq="D")
    date = pd.to_datetime(rng.choice(dates, size=N)).strftime("%Y-%m-%d")

    p_convert = np.array([CONVERSION[(v, d)] for v, d in zip(variant, device)])
    converted = (rng.random(N) < p_convert).astype(int)

    spend = rng.lognormal(SPEND_MU, SPEND_SIGMA, size=N)
    revenue = np.where(converted == 1, np.round(spend, 2), 0.0)

    # Whales: a few very large variant orders (outlier-driven revenue mean)
    whale_pool = np.where((variant == "variant") & (converted == 1))[0]
    whale_idx = rng.choice(whale_pool, size=N_WHALES, replace=False)
    revenue[whale_idx] = WHALE_AMOUNTS

    df = pd.DataFrame(
        {
            "user_id": [f"U{i:06d}" for i in range(1, N + 1)],
            "date": date,
            "variant": variant,
            "device": device,
            "converted": converted,
            "revenue": np.round(revenue, 2),
        }
    )
    df.to_csv("ab_test_sessions.csv", index=False)

    print(f"Wrote ab_test_sessions.csv: {len(df):,} sessions")
    print(df.groupby("variant").agg(users=("user_id", "count")))
    print(df.groupby("variant")["converted"].mean().apply(lambda v: f"{v:.2%}"))
    print(df.groupby("variant")["revenue"].mean().apply(lambda v: f"${v:.2f}"))


if __name__ == "__main__":
    main()
