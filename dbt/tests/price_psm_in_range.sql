SELECT * FROM {{ ref('fct_resale') }}
WHERE price_psm NOT BETWEEN 1500 AND 25000