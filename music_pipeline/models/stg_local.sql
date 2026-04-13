-- models/stg_local.sql
-- Silver layer for local tracks
--
-- Raw data has 2 types of rows:
--   1. Spreadsheet rows → clean titles, no file_path
--   2. Music folder rows → messy titles, HAS file_path
--
-- Our job here:
--   → Keep ONLY spreadsheet rows for song metadata
--   → Filter out bad data rows
--   → Match file_path from folder rows using title similarity
--   → Strip anything in () from filenames before matching
--   → Output ONE clean row per song with file_path attached

WITH

spreadsheet_songs AS (
    SELECT
        TRIM(title)                     AS title,
        INITCAP(TRIM(artist))          AS artist,
        TRIM(album)                     AS album,
        duration_seconds,
        'spreadsheet'                   AS source
    FROM raw_local_tracks
    WHERE file_format = 'spreadsheet'
    AND title IS NOT NULL
    AND title != ''
    AND artist NOT ILIKE '%(unclear%'
    AND artist NOT ILIKE '%check spelling%'
),

folder_files AS (
    SELECT
        file_path,
        file_format,
        duration_seconds                AS file_duration,

        -- Strip everything inside () from filename before matching
        -- Example: "Waka Waka (Time For Africa)" → "waka waka "
        -- Example: "Closer (Official Video)"     → "closer "
        -- Example: "Believer - Imagine Dragons"  → kept as-is
        TRIM(
            LOWER(
                REGEXP_REPLACE(title, '\(.*?\)', '', 'g')
            )
        )                               AS filename_clean

    FROM raw_local_tracks
    WHERE file_format != 'spreadsheet'
    AND file_path IS NOT NULL
)

SELECT DISTINCT ON (LOWER(TRIM(s.title)))
    s.title,
    s.artist,
    s.album,
    COALESCE(s.duration_seconds, f.file_duration) AS duration_seconds,
    f.file_path,
    f.file_format,
    s.source,
    NOW()                               AS loaded_at

FROM spreadsheet_songs s

LEFT JOIN folder_files f
    -- match clean title against cleaned filename
    ON f.filename_clean LIKE '%' || LOWER(TRIM(s.title)) || '%'
    OR f.filename_clean LIKE '%' || LOWER(TRIM(s.artist)) || '%'

ORDER BY LOWER(TRIM(s.title)), f.file_path NULLS LAST