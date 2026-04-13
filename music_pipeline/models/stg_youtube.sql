-- models/stg_youtube.sql
SELECT
    youtube_video_id,

    -- Clean YouTube titles
    -- "Ed Sheeran - Shape of You (Official)" → "Shape of You"
    TRIM(
        REGEXP_REPLACE(
            REGEXP_REPLACE(
                REGEXP_REPLACE(
                    title,
                    '\(Official.*?\)', '', 'gi'  -- remove (Official...)
                ),
                '\(Lyrics.*?\)', '', 'gi'        -- remove (Lyrics...)
            ),
            '^.*? - ', ''                        -- remove "Artist - " prefix
        )
    )                                            AS title,

    channel_name,
    
    (
        COALESCE(
            CAST(SUBSTRING(duration_iso FROM 'PT(?:(\d+)H)') AS INTEGER), 0
        ) * 3600
        +
        COALESCE(
            CAST(SUBSTRING(duration_iso FROM 'PT(?:\d+H)?(\d+)M') AS INTEGER), 0
        ) * 60
        +
        COALESCE(
            CAST(SUBSTRING(duration_iso FROM '(\d+)S') AS INTEGER), 0
        )
    )                                            AS duration_seconds,

    thumbnail_url,
    'youtube'                                    AS source,
    loaded_at

FROM raw_youtube_tracks

WHERE youtube_video_id IS NOT NULL