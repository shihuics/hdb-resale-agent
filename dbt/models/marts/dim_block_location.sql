-- One row per HDB block: its coordinates and the nearest MRT station.
-- Distances are straight-line ("as the crow flies") to the nearest station exit,
-- not walking distance. LRT-only stations are excluded.

WITH blocks AS (
    SELECT block, street_name, postal, latitude, longitude
    FROM {{ ref('block_coords') }}
    WHERE latitude IS NOT NULL
),

exits AS (
    SELECT station, latitude AS exit_lat, longitude AS exit_lon
    FROM {{ ref('mrt_exits') }}
    WHERE NOT is_lrt
),

distances AS (
    SELECT
        b.block, b.street_name, b.postal, b.latitude, b.longitude, e.station,
        -- Haversine formula: distance in metres between two points on the Earth
        2 * 6371000 * asin(sqrt(
              pow(sin(radians(e.exit_lat - b.latitude) / 2), 2)
            + cos(radians(b.latitude)) * cos(radians(e.exit_lat))
            * pow(sin(radians(e.exit_lon - b.longitude) / 2), 2)
        )) AS distance_m
    FROM blocks b
    CROSS JOIN exits e
)

SELECT
    block,
    street_name,
    postal,
    latitude,
    longitude,
    arg_min(station, distance_m) AS nearest_mrt,
    round(min(distance_m))       AS mrt_distance_m
FROM distances
GROUP BY block, street_name, postal, latitude, longitude