-- 002_views: похідні представлення для аналітики та моделі

--------------------------------------------------------------------------------
-- Розгортання тривог по годинах: одна тривога -> N рядків (по годині)
-- Дає спільний ключ для join з погодою.
--------------------------------------------------------------------------------
CREATE VIEW v_alert_hours AS
SELECT
    a.id            AS alert_id,
    a.region_id,
    a.source,
    h.hour_ts,
    kyiv_hour(h.hour_ts)          AS kyiv_hour,
    raid_day(h.hour_ts)           AS raid_day,
    EXTRACT(epoch FROM (
        LEAST(COALESCE(a.finished_at, now()), h.hour_ts + interval '1 hour')
      - GREATEST(a.started_at, h.hour_ts)
    ))/60.0                       AS minutes
FROM alerts a
CROSS JOIN LATERAL generate_series(
        date_trunc('hour', a.started_at),
        date_trunc('hour', COALESCE(a.finished_at, now())),
        interval '1 hour'
    ) AS h(hour_ts);

COMMENT ON VIEW v_alert_hours IS 'Тривоги, розкладені по годинних кошиках, з кількістю хвилин у кожному';

--------------------------------------------------------------------------------
-- Добова агрегація тривог (за raid_day, тобто добою 12:00–12:00)
--------------------------------------------------------------------------------
CREATE VIEW v_alerts_daily AS
WITH hrs AS (
    SELECT region_id, source, raid_day, kyiv_hour, alert_id, minutes
    FROM v_alert_hours
)
SELECT
    r.code                                   AS region_code,
    h.region_id,
    h.source,
    h.raid_day,
    COUNT(DISTINCT h.alert_id)               AS alerts_count,
    ROUND(SUM(h.minutes))                    AS total_minutes,
    ROUND(SUM(h.minutes) FILTER (
        WHERE h.kyiv_hour >= 22 OR h.kyiv_hour < 6))  AS night_minutes,
    ROUND(MAX(per_alert.minutes))            AS longest_alert_minutes
FROM hrs h
JOIN regions r ON r.id = h.region_id
JOIN LATERAL (
    SELECT SUM(h2.minutes) AS minutes
    FROM hrs h2
    WHERE h2.alert_id = h.alert_id
) per_alert ON true
GROUP BY r.code, h.region_id, h.source, h.raid_day;

--------------------------------------------------------------------------------
-- Добова агрегація погоди (за raid_day, щоб збігалося з ніччю нальоту)
--------------------------------------------------------------------------------
CREATE VIEW v_weather_daily AS
SELECT
    l.code                                   AS location_code,
    w.location_id,
    raid_day(w.ts)                           AS raid_day,
    COUNT(*)                                 AS hours_observed,
    AVG(w.temperature_2m)                    AS temp_avg,
    MIN(w.temperature_2m)                    AS temp_min,
    MAX(w.temperature_2m)                    AS temp_max,
    SUM(w.precipitation)                     AS precip_sum,
    AVG(w.cloud_cover)                       AS cloud_avg,
    AVG(w.cloud_cover_low)                   AS cloud_low_avg,
    AVG(w.wind_speed_10m)                    AS wind_avg,
    MAX(w.wind_gusts_10m)                    AS gust_max,
    AVG(w.wind_direction_10m)                AS wind_dir_avg,
    AVG(w.surface_pressure)                  AS pressure_avg,
    AVG(w.relative_humidity_2m)              AS humidity_avg,
    -- нічне вікно 22:00–06:00 за київським часом: саме воно визначає видимість для БпЛА
    AVG(w.cloud_cover)     FILTER (WHERE kyiv_hour(w.ts) >= 22 OR kyiv_hour(w.ts) < 6) AS night_cloud_avg,
    AVG(w.cloud_cover_low) FILTER (WHERE kyiv_hour(w.ts) >= 22 OR kyiv_hour(w.ts) < 6) AS night_cloud_low_avg,
    AVG(w.wind_speed_10m)  FILTER (WHERE kyiv_hour(w.ts) >= 22 OR kyiv_hour(w.ts) < 6) AS night_wind_avg,
    SUM(w.precipitation)   FILTER (WHERE kyiv_hour(w.ts) >= 22 OR kyiv_hour(w.ts) < 6) AS night_precip_sum,
    AVG(w.temperature_2m)  FILTER (WHERE kyiv_hour(w.ts) >= 22 OR kyiv_hour(w.ts) < 6) AS night_temp_avg
FROM weather_hourly w
JOIN weather_locations l ON l.id = w.location_id
GROUP BY l.code, w.location_id, raid_day(w.ts);

--------------------------------------------------------------------------------
-- Погодинна матриця "погода + тривога" — основа для моделі
--------------------------------------------------------------------------------
CREATE VIEW v_hourly_features AS
SELECT
    w.ts,
    raid_day(w.ts)                AS raid_day,
    kyiv_hour(w.ts)               AS kyiv_hour,
    w.temperature_2m, w.precipitation, w.cloud_cover, w.cloud_cover_low,
    w.visibility, w.wind_speed_10m, w.wind_speed_100m, w.wind_direction_10m,
    w.surface_pressure, w.relative_humidity_2m,
    COALESCE(city.minutes, 0)     AS kyiv_city_alert_minutes,
    COALESCE(obl.minutes, 0)      AS kyiv_oblast_alert_minutes,
    (COALESCE(city.minutes,0) > 0) AS kyiv_city_alert
FROM weather_hourly w
JOIN weather_locations l ON l.id = w.location_id AND l.code = 'kyiv'
LEFT JOIN LATERAL (
    SELECT SUM(ah.minutes) AS minutes
    FROM v_alert_hours ah
    JOIN regions r ON r.id = ah.region_id AND r.code = 'kyiv_city'
    WHERE ah.hour_ts = w.ts AND ah.source <> 'volunteer'
) city ON true
LEFT JOIN LATERAL (
    SELECT SUM(ah.minutes) AS minutes
    FROM v_alert_hours ah
    JOIN regions r ON r.id = ah.region_id AND r.code = 'kyiv_oblast'
    WHERE ah.hour_ts = w.ts AND ah.source <> 'volunteer'
) obl ON true;

--------------------------------------------------------------------------------
-- Стан системи: що і за який період завантажено
--------------------------------------------------------------------------------
CREATE VIEW v_coverage AS
SELECT 'alerts:'||a.source||':'||r.code AS stream,
       MIN(a.started_at)  AS from_ts,
       MAX(a.started_at)  AS to_ts,
       COUNT(*)           AS rows
FROM alerts a JOIN regions r ON r.id = a.region_id
GROUP BY 1
UNION ALL
SELECT 'weather:'||w.source||':'||l.code, MIN(w.ts), MAX(w.ts), COUNT(*)
FROM weather_hourly w JOIN weather_locations l ON l.id = w.location_id
GROUP BY 1
UNION ALL
SELECT 'forecast:'||l.code, MIN(f.ts), MAX(f.ts), COUNT(*)
FROM weather_forecast f JOIN weather_locations l ON l.id = f.location_id
GROUP BY 1;
