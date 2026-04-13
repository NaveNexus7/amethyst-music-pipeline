-- models/fct_songs.sql
-- Using songs table as the bridge to join all sources
-- This is more reliable than title matching!

WITH songs_base AS (
    SELECT DISTINCT ON (LOWER(TRIM(title)))
        *
    FROM songs
    ORDER BY LOWER(TRIM(title)), id ASC
),

spotify AS (
    SELECT DISTINCT ON (spotify_id)
        *
    FROM {{ ref('stg_spotify') }}
    ORDER BY spotify_id
),

youtube AS (
    SELECT DISTINCT ON (youtube_video_id)
        *
    FROM {{ ref('stg_youtube') }}
    ORDER BY youtube_video_id
)

SELECT
    ROW_NUMBER() OVER (ORDER BY s_base.title) AS song_id,
    TRIM(s_base.title)                        AS title,
    INITCAP(TRIM(s_base.artist))             AS artist,
    TRIM(s_base.album)                        AS album,
    s_base.duration_seconds,
    s_base.local_file_path,
    s_base.spotify_id,
    sp.artwork_url,
    sp.release_date,
    sp.popularity,          -- ← ADD THIS LINE
    s_base.youtube_video_id,
    yt.thumbnail_url                          AS youtube_thumbnail,
    CURRENT_TIMESTAMP                         AS created_at

FROM songs_base s_base

LEFT JOIN spotify sp
    ON s_base.spotify_id = sp.spotify_id

LEFT JOIN youtube yt
    ON s_base.youtube_video_id = yt.youtube_video_id

WHERE s_base.title IS NOT NULL