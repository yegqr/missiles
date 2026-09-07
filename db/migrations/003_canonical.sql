-- 003_canonical: один авторитетний ряд тривог на регіон
--
-- Проблема, яку розв'язуємо. Тривоги по одній території приходять кількома
-- рядами, що не перекриваються в часі:
--   * м. Київ — офіційний ряд з 15.03.2022; волонтерський (eTryvoga) з 25.02.2022
--   * Київська область — офіційний обласний ряд обривається 04.11.2025, бо
--     з липня 2025 тривоги оголошують ПО РАЙОНАХ. Це не втрата даних, а зміна
--     способу оголошення: обласний ряд після переходу треба ВІДНОВЛЮВАТИ як
--     об'єднання районних інтервалів.
--
-- Нижче — узагальнена склейка: беремо всі внески, зливаємо ті, що перекриваються,
-- і віддаємо один безрозривний ряд з позначкою, звідки взято кожен інтервал.

--------------------------------------------------------------------------------
-- Крок 1: внески в канонічний ряд регіону
--------------------------------------------------------------------------------
CREATE VIEW v_alert_parts AS
WITH official_start AS (
    -- з якого моменту по регіону взагалі є офіційні дані
    SELECT a.region_id, MIN(a.started_at) AS ts
    FROM alerts a WHERE a.source = 'official'
    GROUP BY a.region_id
)
-- (1) офіційні тривоги самого регіону
SELECT a.region_id AS canon_region_id, a.region_id AS src_region_id,
       a.started_at, a.finished_at, a.source, 'own'::text AS part
FROM alerts a
WHERE a.source = 'official'

UNION ALL

-- (2) районні тривоги піднімаємо на рівень області
SELECT r.parent_id, a.region_id, a.started_at, a.finished_at, a.source, 'raion'
FROM alerts a
JOIN regions r ON r.id = a.region_id
WHERE a.source = 'official' AND r.level = 'raion' AND r.parent_id IS NOT NULL

UNION ALL

-- (3) волонтерські дані — ТІЛЬКИ до старту офіційних (перші три тижні війни)
SELECT a.region_id, a.region_id, a.started_at, a.finished_at, a.source, 'pre_official'
FROM alerts a
LEFT JOIN official_start os ON os.region_id = a.region_id
WHERE a.source = 'volunteer'
  AND (os.ts IS NULL OR a.started_at < os.ts);

COMMENT ON VIEW v_alert_parts IS
  'Сирі внески в канонічний ряд: власні офіційні, підняті районні, довоєнний хвіст волонтерських';

--------------------------------------------------------------------------------
-- Крок 2: злиття інтервалів, що перекриваються (gaps and islands)
--------------------------------------------------------------------------------
CREATE VIEW v_alerts_canonical AS
WITH p AS (
    SELECT canon_region_id, started_at,
           COALESCE(finished_at, now()) AS finished_at,
           finished_at IS NULL AS is_open,
           source, part
    FROM v_alert_parts
),
marked AS (
    SELECT *,
           MAX(finished_at) OVER (
               PARTITION BY canon_region_id ORDER BY started_at
               ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prev_end
    FROM p
),
grouped AS (
    SELECT *,
           SUM(CASE WHEN prev_end IS NULL OR started_at > prev_end THEN 1 ELSE 0 END)
               OVER (PARTITION BY canon_region_id ORDER BY started_at) AS island
    FROM marked
)
SELECT
    r.code                              AS region_code,
    g.canon_region_id                   AS region_id,
    MIN(g.started_at)                   AS started_at,
    CASE WHEN bool_or(g.is_open) THEN NULL ELSE MAX(g.finished_at) END AS finished_at,
    ROUND(EXTRACT(epoch FROM (MAX(g.finished_at) - MIN(g.started_at)))/60.0) AS duration_min,
    raid_day(MIN(g.started_at))         AS raid_day,
    -- звідки склеєно: own / raion / pre_official (може бути кілька)
    string_agg(DISTINCT g.part, '+' ORDER BY g.part) AS parts,
    count(*)                            AS merged_from
FROM grouped g
JOIN regions r ON r.id = g.canon_region_id
GROUP BY r.code, g.canon_region_id, g.island;

COMMENT ON VIEW v_alerts_canonical IS
  'Один безрозривний ряд тривог на регіон. Колонка parts показує походження інтервалу.';

--------------------------------------------------------------------------------
-- Крок 3: добові й погодинні представлення поверх канонічного ряду
--------------------------------------------------------------------------------
CREATE VIEW v_canon_hours AS
SELECT
    c.region_id, c.region_code, h.hour_ts,
    kyiv_hour(h.hour_ts) AS kyiv_hour,
    raid_day(h.hour_ts)  AS raid_day,
    EXTRACT(epoch FROM (
        LEAST(COALESCE(c.finished_at, now()), h.hour_ts + interval '1 hour')
      - GREATEST(c.started_at, h.hour_ts)))/60.0 AS minutes,
    c.started_at AS alert_started_at
FROM v_alerts_canonical c
CROSS JOIN LATERAL generate_series(
    date_trunc('hour', c.started_at),
    date_trunc('hour', COALESCE(c.finished_at, now())),
    interval '1 hour') AS h(hour_ts);

CREATE VIEW v_canon_daily AS
SELECT region_code, region_id, raid_day,
       COUNT(DISTINCT alert_started_at)  AS alerts_count,
       ROUND(SUM(minutes))               AS total_minutes,
       ROUND(SUM(minutes) FILTER (WHERE kyiv_hour >= 22 OR kyiv_hour < 6)) AS night_minutes
FROM v_canon_hours
GROUP BY region_code, region_id, raid_day;

-- Матриця для моделі тепер спирається на канонічний ряд
DROP VIEW IF EXISTS v_hourly_features;
CREATE VIEW v_hourly_features AS
SELECT
    w.ts,
    raid_day(w.ts)  AS raid_day,
    kyiv_hour(w.ts) AS kyiv_hour,
    w.temperature_2m, w.precipitation, w.cloud_cover, w.cloud_cover_low,
    w.visibility, w.wind_speed_10m, w.wind_speed_100m, w.wind_direction_10m,
    w.surface_pressure, w.relative_humidity_2m,
    COALESCE(city.minutes, 0) AS kyiv_city_alert_minutes,
    COALESCE(obl.minutes, 0)  AS kyiv_oblast_alert_minutes,
    (COALESCE(city.minutes, 0) > 0) AS kyiv_city_alert
FROM weather_hourly w
JOIN weather_locations l ON l.id = w.location_id AND l.code = 'kyiv'
LEFT JOIN LATERAL (
    SELECT SUM(ch.minutes) AS minutes FROM v_canon_hours ch
    WHERE ch.hour_ts = w.ts AND ch.region_code = 'kyiv_city') city ON true
LEFT JOIN LATERAL (
    SELECT SUM(ch.minutes) AS minutes FROM v_canon_hours ch
    WHERE ch.hour_ts = w.ts AND ch.region_code = 'kyiv_oblast') obl ON true;
