# A/B Test Power Analysis, SRM & Revenue Uplift Audit

## Executive decision memo

**Verdict: DO NOT SHIP the new checkout.**

A naive read of this experiment says ship it: the variant converts
+2.4% better in relative terms (10.17% vs 9.94%) and revenue per user is
up 2.7% ($13.46 vs $13.11). Both arrows are green. Both are meaningless —
the experiment itself is broken, and the audit below shows why a p-value
check alone would have shipped a broken feature.

## What was tested

A new one-page checkout (variant) against the current checkout (control),
50,000 sessions over 14 days (2026-11-03 to 2026-11-16), intended 50/50
split. The dataset is simulated (seeded — see `generate_data.py`) with the
flaws a real experiment can carry, so the audit pipeline runs on data with
known ground truth.

## Finding 1 — Sample Ratio Mismatch: the randomisation is broken

| | Users | Share |
|---|---|---|
| Control | 25,400 | 50.8% |
| Variant | 24,600 | 49.2% |

The intended split was 50/50. Chi-square goodness-of-fit:
**chi² = 12.80, p = 0.00035**. The imbalance is consistent across all 14
days (see Query 4 in `queries.sql`), so this is a systematic assignment or
telemetry fault, not a one-day glitch. The two groups are not comparable,
and **no comparison built on this split is valid** — this alone kills the
test, whatever the p-values say.

## Finding 2 — Conversion uplift is not significant

| | Conversion rate |
|---|---|
| Control | 9.94% (2,524 / 25,400) |
| Variant | 10.17% (2,503 / 24,600) |
| Uplift | **+0.24pp (+2.4% relative)** |

Two-proportion z-test: **z = 0.884, p = 0.377**. The 95% confidence
interval for the uplift is **[-0.29pp, +0.77pp]** — it includes zero and
negative values. The "uplift" is indistinguishable from noise.

## Finding 3 — Revenue: both tests agree there is no effect

Revenue per user is heavily skewed (median $0.00 in both arms — most
sessions don't buy), so the audit runs both a parametric and a
non-parametric test:

| | Control | Variant |
|---|---|---|
| Mean revenue / user | $13.11 | $13.46 |
| Median | $0.00 | $0.00 |
| SD | $47.66 | $56.26 |
| Max order | $749.25 | $2,600.00 |
| Total revenue | $333,034.48 | $331,114.13 |

- Welch's t-test: **t = 0.746, p = 0.456** — not significant.
- Mann-Whitney U: **U = 313,094,460, p = 0.423** — not significant.

The two tests agree: there is no revenue effect. The $0.35 mean gap is
noise against standard deviations near $50, and the variant's longer tail
(a few $1,500–$2,600 orders) moves the mean without moving the
distribution. Note also that total revenue is actually *lower* in the
variant ($331,114 vs $333,034) — the per-user figure only looks better
because the variant arm has fewer users.

## Finding 4 — The test was badly underpowered

- Power at the observed uplift: **14.1%** — the test had almost no chance
  of detecting an effect of this size.
- Minimum detectable effect at 80% power: **0.75pp**, more than 3× the
  observed 0.24pp.
- Sessions needed to detect the observed uplift at 80% power: **248,461
  per arm (~497,000 total)** — roughly 10× what was run.

## Finding 5 — No segment supports a rollout

| Segment | Control | Variant | Uplift | p | Power |
|---|---|---|---|---|---|
| Mobile | 8.82% | 9.25% | +0.43pp | 0.195 | 25% |
| Desktop | 11.59% | 11.56% | −0.03pp | 0.939 | 3% |

Neither segment is significant and both are underpowered. There is no
subgroup to ship to instead.

## Recommendation

1. **Do not ship.** The SRM alone invalidates the result; the effect
   isn't significant, isn't powered, and doesn't hold in any segment.
2. **Fix the assignment first.** Audit the randomiser and the telemetry
   pipeline — find why the split delivered 50.8/49.2 every day — and add
   an automated SRM gate that halts analysis when the split check fails.
3. **Re-run properly:** pre-register the analysis (SRM gate, two-proportion
   z-test for conversion, Welch's t *and* Mann-Whitney U for revenue),
   and size it for the effect that matters — ~500k sessions to detect a
   0.25pp lift, or accept a 0.75pp MDE and power for that instead.

## How to run

```bash
python generate_data.py    # rebuild the dataset (seeded, reproducible)
pip install -r requirements.txt
python ab_test_audit.py
```

The script loads the CSV into SQLite, runs the four aggregations in
`queries.sql`, then runs the SRM chi-square test, the conversion z-test
and CI, Welch's t and Mann-Whitney U on revenue, the power/MDE
calculations, and the segment analysis. It saves
`revenue_distribution.png`, `uplift_chart.png`, and `summary_stats.csv`.

## Contents

| File | What it is |
|---|---|
| `ab_test_sessions.csv` | 50,000 simulated sessions (user, date, variant, device, converted, revenue) |
| `generate_data.py` | The seeded simulation, including the built-in SRM and whale orders |
| `queries.sql` | SQL aggregations: variant summary, SRM check, segments, daily volume |
| `ab_test_audit.py` | The full audit: SRM test, z-test, Welch + Mann-Whitney, power, MDE, charts |
| `requirements.txt` | pandas, scipy, matplotlib, numpy |
| `revenue_distribution.png` | Revenue per converted user, log scale |
| `uplift_chart.png` | Conversion uplift by segment with 95% CI and the MDE line |
| `summary_stats.csv` | Headline metrics |

## Limitations

- The dataset is simulated, not from a live experiment; the flaws are
  planted deliberately so the pipeline's checks are exercised.
- Power and MDE use normal approximations, standard for this sample size.
- Revenue is in USD; the analysis is currency-agnostic.
