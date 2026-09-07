-- 018: «невідомо» перестає бути «атаки не було»
--
-- v_daily_features робила COALESCE(l.attacked_kyiv, false). Для 303 діб
-- 2022-2023, де джерело взагалі нічого не стверджувало, це перетворювало
-- відсутність інформації на впевнене заперечення — той самий клас брудних
-- даних, від якого застерігає METHODOLOGY §7, лише в іншому місці.
-- Тепер y_attacked = NULL там, де твердження немає, і споживач мусить
-- вирішити явно. ml/dataset.py такі доби відкидає.
--
-- Заразом: alerts_count більше не рахує ту саму тривогу двічі. Тривога, що
-- перетинає 12:00, потрапляє у дві доби нальоту (це правильно для хвилин),
-- але як ПОДІЯ вона одна, і має рахуватись у добі свого початку — інакше
-- сума подій по місту (2492) перевищує кількість самих тривог (2403).

DROP VIEW IF EXISTS v_prediction_scores;

CREATE OR REPLACE VIEW v_canon_daily AS
SELECT region_code, region_id, raid_day,
       -- подія рахується в добі СВОГО ПОЧАТКУ, а не в кожній, куди зазирнула
       COUNT(DISTINCT alert_started_at)
         FILTER (WHERE raid_day(alert_started_at) = raid_day) AS alerts_count,
       ROUND(SUM(minutes))                                    AS total_minutes,
       COALESCE(ROUND(SUM(minutes) FILTER (WHERE kyiv_hour >= 22 OR kyiv_hour < 6)), 0)
                                                              AS night_minutes
FROM v_canon_hours
GROUP BY region_code, region_id, raid_day;

COMMENT ON VIEW v_canon_daily IS
  'Добові агрегати тривог. total_minutes/night_minutes діляться між добами '
  'нальоту пропорційно годинам; alerts_count рахує подію один раз — у добі, '
  'коли тривога почалась.';

CREATE OR REPLACE VIEW v_daily_features AS
SELECT
    c.day AS raid_day,
    c.dow, c.month, c.night_hours, c.heating_season,
    c.holiday_ua, COALESCE(c.holiday_ua_w, 0) AS holiday_ua_w,
    c.holiday_ru, COALESCE(c.holiday_ru_w, 0) AS holiday_ru_w,
    COALESCE(pl.alerts_count, 0)        AS alerts_prev,
    COALESCE(pl.alert_minutes, 0)       AS alert_minutes_prev,
    COALESCE(pl.drone_tracks_kyiv, 0)   AS drone_tracks_prev,
    COALESCE(pl.missile_tracks_kyiv, 0) AS missile_tracks_prev,
    COALESCE(pl.drones_launched_ua, 0)  AS drones_launched_ua_prev,
    COALESCE(pr.mig31k_takeoffs, 0)     AS mig31k_prev,
    COALESCE(pr.strategic_takeoffs, 0)  AS strategic_prev,
    COALESCE(pr.kalibr_signals, 0)      AS kalibr_prev,
    fw.night_cloud_low_avg, fw.night_wind_avg, fw.night_temp_avg,
    fw.night_precip_sum,
    l.attacked_kyiv                     AS y_attacked,   -- NULL = невідомо
    COALESCE(l.drone_tracks_kyiv, 0)    AS y_drone_tracks,
    COALESCE(l.missile_tracks_kyiv, 0)  AS y_missile_tracks,
    COALESCE(l.alert_minutes, 0)        AS y_alert_minutes,
    COALESCE(rd.mig31k_takeoffs, 0)     AS mig31k_same_window
FROM calendar_days c
LEFT JOIN v_daily_labels     l  ON l.raid_day  = c.day
LEFT JOIN v_daily_labels     pl ON pl.raid_day = c.day - 1
LEFT JOIN v_readiness_daily  pr ON pr.raid_day = c.day - 1
LEFT JOIN v_readiness_daily  rd ON rd.raid_day = c.day
LEFT JOIN v_weather_daily    fw ON fw.raid_day = c.day AND fw.location_code = 'kyiv'
WHERE c.day >= '2022-02-24';

COMMENT ON VIEW v_daily_features IS
  'Ознаки *_prev — усе, відоме до відсічки 12:00. y_* — цільові. '
  'y_attacked = NULL означає «джерело нічого не стверджувало», а не «ні». '
  'night_* — ФАКТИЧНА погода за вікно прогнозу, тобто витік: у продакшн-'
  'конфігурації блок погоди вимкнено.';

CREATE VIEW v_prediction_scores AS
WITH last_pred AS (
    SELECT DISTINCT ON (raid_day, target, horizon)
           raid_day, target, horizon, p, issued_at, model
    FROM predictions ORDER BY raid_day, target, horizon, issued_at DESC
),
fact AS (
    SELECT raid_day, y_attacked AS attacked,
           y_alert_minutes >= 30 AS alert30,
           (y_drone_tracks + y_missile_tracks) > 0
             AND (y_alert_minutes >= 480 OR y_drone_tracks >= 15) AS massive
    FROM v_daily_features
)
SELECT lp.raid_day, lp.target, lp.horizon, lp.p, lp.issued_at, lp.model,
       CASE lp.target WHEN 'attacked' THEN f.attacked
                      WHEN 'alert30'  THEN f.alert30
                      WHEN 'massive'  THEN f.massive END AS факт,
       (lp.p - (CASE lp.target WHEN 'attacked' THEN f.attacked::int
                               WHEN 'alert30'  THEN f.alert30::int
                               WHEN 'massive'  THEN f.massive::int END)) ^ 2 AS brier
FROM last_pred lp JOIN fact f ON f.raid_day = lp.raid_day
WHERE lp.raid_day < raid_day(now())
  AND (lp.target <> 'attacked' OR f.attacked IS NOT NULL);
