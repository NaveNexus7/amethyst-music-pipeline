-- models/stg_spotify.sql
-- "stg" means staging — this is Silver layer
-- We're cleaning raw_spotify_tracks here

SELECT
    spotify_id,
    TRIM(title)                          AS title,
    INITCAP(TRIM(artist))               AS artist,
    TRIM(album)                          AS album,
    ROUND(duration_ms / 1000.0, 2)      AS duration_seconds,
    release_date,
    artwork_url,
    popularity,              -- ← ADD THIS
    'spotify'                            AS source,
    loaded_at
FROM raw_spotify_tracks
WHERE spotify_id IS NOT NULL

-- only keep rows that have a spotify_id
