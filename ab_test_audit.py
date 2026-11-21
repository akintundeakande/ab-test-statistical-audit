"""A/B Test Power Analysis, SRM & Revenue Uplift Audit.

End-to-end statistical audit of a flawed e-commerce A/B experiment:

  1. Data validation & SRM detection — SQL aggregates plus a chi-square
     goodness-of-fit test on the intended 50/50 split.
  2. Hypothesis testing — two-proportion z-test for conversion uplift;
     Welch's t-test AND Mann-Whitney U for skewed revenue per user.
  3. Power & MDE — statistical power at the observed effect, the minimum
     detectable effect at 80% power, and the sample size a re-run needs.

Inputs (same folder):
    ab_test_sessions.csv - user_id, date, variant, device, converted, revenue
    queries.sql          - the SQL aggregations this audit runs
    generate_data.py     - how the dataset was simulated (seeded)

Outputs:
    revenue_distribution.png - revenue per converted user, log scale
    uplift_chart.png         - conversion uplift by segment with 95% CI
    summary_stats.csv        - the headline metrics

Usage:
    python generate_data.py   # build the dataset (already committed)
    pip install -r requirements.txt
    python ab_test_audit.py
"""

import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy import stats  # noqa: E402

DATA_DIR = Path(__file__).parent
ALPHA = 0.05
TARGET_POWER = 0.80


def two_proportion_ztest(x1: int, n1: int, x2: int, n2: int):
    """Two-sided two-proportion z-test (pooled SE). Returns (z, p)."""
    p_pool = (x1 + x2) / (n1 + n2)
    se = np.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    z = (x2 / n2 - x1 / n1) / se
    return z, 2 * (1 - stats.norm.cdf(abs(z)))


def two_proportion_ci(x1: int, n1: int, x2: int, n2: int, alpha: float = ALPHA):
    """Wald 95% CI for the difference in proportions (unpooled SE)."""
    p1, p2 = x1 / n1, x2 / n2
    se = np.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    z = stats.norm.ppf(1 - alpha / 2)
    return (p2 - p1) - z * se, (p2 - p1) + z * se


def power_two_prop(p1: float, p2: float, n1: int, n2: int, alpha: float = ALPHA):
    """Normal-approximation power of a two-sided two-proportion test."""
    se = np.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    delta = abs(p2 - p1)
    z_alpha = stats.norm.ppf(1 - alpha / 2)
    return float(stats.norm.cdf(delta / se - z_alpha))


def mde_two_prop(p0: float, n1: int, n2: int, alpha: float = ALPHA,
                 power: float = TARGET_POWER):
    """Minimum detectable effect (proportion points) at the given power."""
    se0 = np.sqrt(p0 * (1 - p0) * (1 / n1 + 1 / n2))
    z = stats.norm.ppf(1 - alpha / 2) + stats.norm.ppf(power)
    return z * se0


def required_n_per_arm(p0: float, mde: float, alpha: float = ALPHA,
                       power: float = TARGET_POWER):
    """Sessions per arm needed to detect `mde` at the given power."""
    z = stats.norm.ppf(1 - alpha / 2) + stats.norm.ppf(power)
    return int(np.ceil(2 * p0 * (1 - p0) * (z / mde) ** 2))


def run_sql(con: sqlite3.Connection) -> None:
    sql = (DATA_DIR / "queries.sql").read_text()
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    for i, stmt in enumerate(statements, start=1):
        clean = "\n".join(
            line for line in stmt.splitlines()
            if not line.strip().startswith("--")
        )
        print(f"\n-- Query {i} --")
        print(pd.read_sql_query(clean, con).to_string(index=False))


def main() -> None:
    df = pd.read_csv(DATA_DIR / "ab_test_sessions.csv")
    con = sqlite3.connect(":memory:")
    df.to_sql("sessions", con, index=False)

    print("== SQL aggregations ==")
    run_sql(con)

    control = df[df["variant"] == "control"]
    variant = df[df["variant"] == "variant"]
    n_c, n_v = len(control), len(variant)
    x_c, x_v = int(control["converted"].sum()), int(variant["converted"].sum())
    p_c, p_v = x_c / n_c, x_v / n_v

    # --- 1. SRM: chi-square goodness of fit on the 50/50 split --------
    chi2, p_srm = stats.chisquare([n_c, n_v], [len(df) / 2, len(df) / 2])
    print("\n== 1. Sample Ratio Mismatch ==")
    print(f"  Intended split: 50/50 ({len(df) // 2:,} each)")
    print(f"  Observed: control {n_c:,} ({n_c / len(df):.1%}), "
          f"variant {n_v:,} ({n_v / len(df):.1%})")
    print(f"  Chi-square GOF: chi2 = {chi2:.2f}, p = {p_srm:.5f}")
    print("  SRM DETECTED — randomisation is broken, do not trust the split"
          if p_srm < ALPHA else "  No SRM detected")

    # --- 2. Conversion uplift ------------------------------------------
    z, p_conv = two_proportion_ztest(x_c, n_c, x_v, n_v)
    lo, hi = two_proportion_ci(x_c, n_c, x_v, n_v)
    print("\n== 2. Conversion uplift (two-proportion z-test) ==")
    print(f"  Control: {p_c:.2%} ({x_c:,}/{n_c:,})")
    print(f"  Variant: {p_v:.2%} ({x_v:,}/{n_v:,})")
    print(f"  Uplift: {(p_v - p_c) * 100:+.2f}pp "
          f"({(p_v / p_c - 1) * 100:+.1f}% relative)")
    print(f"  95% CI for uplift: [{lo * 100:+.2f}pp, {hi * 100:+.2f}pp]")
    print(f"  z = {z:.3f}, p = {p_conv:.4f} — "
          + ("significant" if p_conv < ALPHA else "NOT significant")
          + " at alpha = 0.05")

    # --- 3. Revenue per user: Welch's t vs Mann-Whitney U ---------------
    rev_c, rev_v = control["revenue"], variant["revenue"]
    t, p_welch = stats.ttest_ind(rev_v, rev_c, equal_var=False)
    u, p_mwu = stats.mannwhitneyu(rev_v, rev_c, alternative="two-sided")
    print("\n== 3. Revenue per user (skewed: mostly $0, long tail) ==")
    print(f"  Control: mean ${rev_c.mean():.2f}, median ${rev_c.median():.2f}, "
          f"SD ${rev_c.std():.2f}, max ${rev_c.max():,.2f}")
    print(f"  Variant: mean ${rev_v.mean():.2f}, median ${rev_v.median():.2f}, "
          f"SD ${rev_v.std():.2f}, max ${rev_v.max():,.2f}")
    print(f"  Mean difference: ${rev_v.mean() - rev_c.mean():+.2f}")
    print(f"  Welch's t-test: t = {t:.3f}, p = {p_welch:.4f} — "
          + ("significant" if p_welch < ALPHA else "NOT significant"))
    print(f"  Mann-Whitney U: U = {u:,.0f}, p = {p_mwu:.4f} — "
          + ("significant" if p_mwu < ALPHA else "NOT significant"))
    if (p_welch < ALPHA) != (p_mwu < ALPHA):
        print("  DIVERGENCE: the parametric test and the rank test disagree — "
              "the mean gap is outlier-driven, not a distributional shift.")

    # --- 4. Power, MDE, required sample --------------------------------
    power = power_two_prop(p_c, p_v, n_c, n_v)
    mde = mde_two_prop(p_c, n_c, n_v)
    n_needed = required_n_per_arm(p_c, abs(p_v - p_c))
    print("\n== 4. Power & minimum detectable effect (conversion) ==")
    print(f"  Power at the observed uplift: {power:.1%}")
    print(f"  MDE at 80% power: {mde * 100:.2f}pp "
          f"(observed uplift {(p_v - p_c) * 100:.2f}pp is "
          f"{'below' if abs(p_v - p_c) < mde else 'above'} the MDE)")
    print(f"  Sessions per arm needed to detect the observed uplift "
          f"at 80% power: {n_needed:,} (~{2 * n_needed:,} total)")
    print("  UNDERPOWERED" if power < TARGET_POWER else "  Adequately powered")

    # --- 5. Segment analysis -------------------------------------------
    print("\n== 5. Segment analysis (by device) ==")
    rows = []
    for device in ["mobile", "desktop"]:
        c = control[control["device"] == device]
        v = variant[variant["device"] == device]
        xc, xv = int(c["converted"].sum()), int(v["converted"].sum())
        nc, nv = len(c), len(v)
        pc, pv = xc / nc, xv / nv
        zs, ps = two_proportion_ztest(xc, nc, xv, nv)
        pw = power_two_prop(pc, pv, nc, nv)
        lo_s, hi_s = two_proportion_ci(xc, nc, xv, nv)
        flag = "UNDER-POWERED" if pw < TARGET_POWER else "powered"
        print(f"  {device}: control {pc:.2%} vs variant {pv:.2%} "
              f"({(pv - pc) * 100:+.2f}pp, 95% CI "
              f"[{lo_s * 100:+.2f}, {hi_s * 100:+.2f}]pp, p = {ps:.4f}, "
              f"power = {pw:.0%}) — {flag}")
        rows.append({"segment": device, "uplift_pp": (pv - pc) * 100,
                     "ci_lo_pp": lo_s * 100, "ci_hi_pp": hi_s * 100,
                     "p_value": ps, "power": pw})
    rows.append({"segment": "overall", "uplift_pp": (p_v - p_c) * 100,
                 "ci_lo_pp": lo * 100, "ci_hi_pp": hi * 100,
                 "p_value": p_conv, "power": power})

    # --- Charts ---------------------------------------------------------
    converted_only = df[df["converted"] == 1]
    fig, ax = plt.subplots(figsize=(10, 5))
    bins = np.logspace(np.log10(10), np.log10(2500), 30)
    for label, sub in [("Control", converted_only[converted_only["variant"] == "control"]),
                       ("Variant", converted_only[converted_only["variant"] == "variant"])]:
        ax.hist(sub["revenue"], bins=bins, alpha=0.6, label=label)
        ax.axvline(sub["revenue"].median(), linestyle="--", linewidth=1)
    ax.set_xscale("log")
    ax.set_xlabel("Revenue per converted user ($, log scale)")
    ax.set_ylabel("Number of users")
    ax.set_title("Revenue per converted user — same shape, variant has a longer tail")
    ax.legend()
    plt.tight_layout()
    plt.savefig(DATA_DIR / "revenue_distribution.png", dpi=150)
    plt.close()

    seg = pd.DataFrame(rows)
    order = ["overall", "mobile", "desktop"]
    seg["segment"] = pd.Categorical(seg["segment"], categories=order, ordered=True)
    seg = seg.sort_values("segment")
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.errorbar(seg["uplift_pp"], seg["segment"],
                xerr=[seg["uplift_pp"] - seg["ci_lo_pp"],
                      seg["ci_hi_pp"] - seg["uplift_pp"]],
                fmt="o", capsize=5)
    ax.axvline(0, color="grey", linestyle="--")
    ax.axvline(mde * 100, color="red", linestyle=":", label=f"MDE at 80% power ({mde * 100:.2f}pp)")
    ax.set_xlabel("Conversion uplift (percentage points, variant − control)")
    ax.set_title("Conversion uplift by segment with 95% CI — none clears zero")
    ax.legend()
    plt.tight_layout()
    plt.savefig(DATA_DIR / "uplift_chart.png", dpi=150)
    plt.close()

    # --- Summary ---------------------------------------------------------
    summary = pd.DataFrame([{
        "metric": "srm_chi2_p",
        "value": p_srm,
    }, {
        "metric": "conversion_uplift_pp",
        "value": (p_v - p_c) * 100,
    }, {
        "metric": "conversion_z_p",
        "value": p_conv,
    }, {
        "metric": "revenue_welch_p",
        "value": p_welch,
    }, {
        "metric": "revenue_mannwhitney_p",
        "value": p_mwu,
    }, {
        "metric": "power_at_observed_uplift",
        "value": power,
    }, {
        "metric": "mde_pp_at_80pct_power",
        "value": mde * 100,
    }, {
        "metric": "sessions_per_arm_needed",
        "value": n_needed,
    }])
    summary.to_csv(DATA_DIR / "summary_stats.csv", index=False)
    print("\nSaved: revenue_distribution.png, uplift_chart.png, summary_stats.csv")


if __name__ == "__main__":
    main()
