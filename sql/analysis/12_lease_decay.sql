-- How price psm falls as remaining lease shortens (2024 onwards)
SELECT FLOOR(remaining_lease_years / 5) * 5 AS lease_bucket_start,
       COUNT(*) AS txns, median(price_psm) AS median_psm
FROM stg_resale WHERE txn_month >= DATE '2024-01-01'
GROUP BY 1 ORDER BY 1;