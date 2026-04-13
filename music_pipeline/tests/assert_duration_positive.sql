-- Custom test: duration_seconds must always be positive
-- If this query returns ANY rows, the test FAILS
-- dbt tests work by: if SELECT returns rows = FAIL, no rows = PASS

SELECT
    title,
    duration_seconds
FROM {{ ref('fct_songs') }}
WHERE duration_seconds IS NOT NULL
AND duration_seconds <= 0