# Table: fct_resale
One row per HDB resale transaction, registrations from Jan 2017.

## Columns
- txn_month (DATE): first day of the registration month
- txn_year (INT), txn_quarter (INT)
- town (TEXT): upper case, e.g. 'TAMPINES', 'ANG MO KIO'
- flat_type (TEXT): '1 ROOM' … '5 ROOM', 'EXECUTIVE', 'MULTI-GENERATION'
- block, street_name (TEXT)
- storey_mid (DOUBLE): midpoint of the storey range, e.g. 5.0 for '04 TO 06'
- floor_area_sqm (DOUBLE)
- flat_model (TEXT): e.g. 'Model A', 'Improved', 'DBSS'
- lease_start_year (INT), remaining_lease_years (DOUBLE), flat_age_years (INT)
- resale_price (DOUBLE): S$
- price_psm (DOUBLE): S$ per square metre
- latitude, longitude (DOUBLE): block location
- nearest_mrt (TEXT): nearest MRT station, e.g. 'ANG MO KIO MRT STATION'
- mrt_distance_m (DOUBLE): straight-line distance in metres to the nearest MRT exit; NULL if the block couldn't be located

## Conventions
- "Price" means median resale_price unless the user says average.
- "Recent" or "last 12 months" is relative to MAX(txn_month), not today.
- Always report the transaction count next to a median.
- Town and flat_type values are upper case.
- "Near an MRT" means mrt_distance_m <= 500 unless the user gives a distance.

## Examples
Q: Median 4-room price in Tampines in 2025?
```sql
SELECT median(resale_price) AS median_price, COUNT(*) AS txns
FROM fct_resale
WHERE town = 'TAMPINES' AND flat_type = '4 ROOM' AND txn_year = 2025
```

Q: Which 3 towns had the biggest year-over-year rise in median 5-room price from 2023 to 2024?
```sql
WITH y AS (
  SELECT town, txn_year, median(resale_price) AS m
  FROM fct_resale
  WHERE flat_type = '5 ROOM' AND txn_year IN (2023, 2024)
  GROUP BY 1, 2)
SELECT town,
       MAX(m) FILTER (WHERE txn_year = 2024) / MAX(m) FILTER (WHERE txn_year = 2023) - 1 AS yoy
FROM y GROUP BY town ORDER BY yoy DESC LIMIT 3
```