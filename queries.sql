-- A/B test audit queries (SQLite dialect). Run against ab_test_sessions.csv
-- loaded as a table named `sessions`.

-- 1. Variant-level summary: users, conversions, conversion rate, revenue per user
SELECT
  variant,
  COUNT(*) AS users,
  SUM(converted) AS conversions,
  ROUND(100.0 * SUM(converted) / COUNT(*), 2) AS conversion_rate_pct,
  ROUND(SUM(revenue) / COUNT(*), 2) AS revenue_per_user,
  ROUND(SUM(revenue), 2) AS total_revenue
FROM sessions
GROUP BY variant;

-- 2. SRM check: observed split vs the intended 50/50
SELECT
  variant,
  COUNT(*) AS users,
  25000 AS expected_users,
  ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM sessions), 1) AS pct_of_sessions
FROM sessions
GROUP BY variant;

-- 3. Segment summary by device
SELECT
  variant,
  device,
  COUNT(*) AS users,
  SUM(converted) AS conversions,
  ROUND(100.0 * SUM(converted) / COUNT(*), 2) AS conversion_rate_pct,
  ROUND(SUM(revenue) / COUNT(*), 2) AS revenue_per_user
FROM sessions
GROUP BY variant, device
ORDER BY device, variant;

-- 4. Daily volume by variant (assignment stability over time)
SELECT
  date,
  variant,
  COUNT(*) AS users
FROM sessions
GROUP BY date, variant
ORDER BY date, variant;
