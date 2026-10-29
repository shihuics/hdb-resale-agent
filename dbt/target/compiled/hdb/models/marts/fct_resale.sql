SELECT
    *,
    year(txn_month)                    AS txn_year,
    quarter(txn_month)                 AS txn_quarter,
    year(txn_month) - lease_start_year AS flat_age_years
FROM "hdb"."main"."stg_resale"