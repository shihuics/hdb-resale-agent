SELECT
    r.*,
    year(r.txn_month)                      AS txn_year,
    quarter(r.txn_month)                   AS txn_quarter,
    year(r.txn_month) - r.lease_start_year AS flat_age_years,
    l.postal,
    l.latitude,
    l.longitude,
    l.nearest_mrt,
    l.mrt_distance_m
FROM {{ ref('stg_resale') }} r
LEFT JOIN {{ ref('dim_block_location') }} l
    ON r.block = l.block AND r.street_name = l.street_name
 