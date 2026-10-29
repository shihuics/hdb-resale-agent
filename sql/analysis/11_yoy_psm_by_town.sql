-- Year-over-year change in median price psm, 4-room, by town
WITH yearly AS (
  SELECT town, year(txn_month) AS yr, median(price_psm) AS med_psm
  FROM stg_resale WHERE flat_type = '4 ROOM' GROUP BY 1, 2
)
SELECT town, yr, med_psm,
       med_psm / LAG(med_psm) OVER (PARTITION BY town ORDER BY yr) - 1 AS yoy_change
FROM yearly ORDER BY town, yr;