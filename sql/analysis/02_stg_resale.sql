CREATE OR REPLACE VIEW stg_resale AS
SELECT
    strptime(month || '-01', '%Y-%m-%d')::DATE AS txn_month,
    town, flat_type, block, street_name, storey_range,
    (CAST(split_part(storey_range, ' TO ', 1) AS INT)
     + CAST(split_part(storey_range, ' TO ', 2) AS INT)) / 2.0 AS storey_mid,
    CAST(floor_area_sqm AS DOUBLE) AS floor_area_sqm,
    flat_model,
    CAST(lease_commence_date AS INT) AS lease_start_year,
    CAST(regexp_extract(remaining_lease, '(\d+) year', 1) AS INT)
      + COALESCE(TRY_CAST(NULLIF(regexp_extract(remaining_lease, '(\d+) month', 1), '') AS INT), 0) / 12.0
      AS remaining_lease_years,
    CAST(resale_price AS DOUBLE) AS resale_price,
    CAST(resale_price AS DOUBLE) / CAST(floor_area_sqm AS DOUBLE) AS price_psm
FROM raw_resale;