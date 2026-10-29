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

## Conventions
- "Price" means median resale_price unless the user says average.
- "Recent" or "last 12 months" is relative to MAX(txn_month), not today.
- Always report the transaction count next to a median.
- Town and flat_type values are upper case.

## Examples
Q: Median 4-room price in Tampines in 2025?
```sql
SELECT median(resale_price) AS median_price, COUNT(*) AS txns
FROM fct_resale
WHERE town = 'TAMPINES' AND flat_type = '4 ROOM' AND txn_year = 2025
```