-- 017: тривалість загрози МіГ-31К рахується парою «зліт → відбій» за ЧАСОМ
--
-- Було: max(відбій) - min(зліт) У МЕЖАХ ОДНІЄЇ raid_day. Але raid_day ріже
-- добу о 12:00 за Києвом, а МіГ-31К злітає й отримує відбій саме навколо
-- полудня — пара регулярно опинялась у різних кошиках. Наслідок: 2 від'ємні
-- значення (до -1381 хв, коли зліт відняли від ЧУЖОГО, більш раннього відбою)
-- і 17% відбоїв, спарованих не зі своїм зльотом.
--
-- Стало: кожен зліт шукає НАЙБЛИЖЧИЙ відбій після себе, у межах 12 годин.
-- Тривалість приписується добі ЗЛЬОТУ — саме тоді сигнал і був доступний.

DROP VIEW IF EXISTS v_prediction_scores;
DROP VIEW IF EXISTS v_daily_features;
DROP VIEW IF EXISTS v_readiness_daily;

CREATE VIEW v_readiness_daily AS
WITH mig_up AS (
    SELECT r.ts, r.raid_day,
           (SELECT min(s.ts) FROM readiness_signals s
             WHERE s.platform = 'mig31k' AND s.is_standdown
               AND s.ts > r.ts AND s.ts < r.ts + interval '12 hours') AS down_ts
    FROM readiness_signals r
    WHERE r.platform = 'mig31k' AND NOT r.is_standdown
),
mig AS (
    SELECT raid_day, count(*) AS takeoffs,
           avg(EXTRACT(epoch FROM (down_ts - ts)) / 60.0) AS threat_minutes,
           count(*) FILTER (WHERE down_ts IS NULL)        AS unresolved
    FROM mig_up GROUP BY raid_day
),
other AS (
    SELECT raid_day,
           count(*) FILTER (WHERE platform IN ('tu95','tu160')) AS strategic_takeoffs,
           count(*) FILTER (WHERE platform = 'kalibr_ship')     AS kalibr_signals
    FROM readiness_signals GROUP BY raid_day
)
SELECT COALESCE(m.raid_day, o.raid_day)          AS raid_day,
       COALESCE(m.takeoffs, 0)                   AS mig31k_takeoffs,
       COALESCE(o.strategic_takeoffs, 0)         AS strategic_takeoffs,
       COALESCE(o.kalibr_signals, 0)             AS kalibr_signals,
       m.threat_minutes                          AS mig31k_threat_minutes,
       COALESCE(m.unresolved, 0)                 AS mig31k_unresolved
FROM mig m FULL JOIN other o ON o.raid_day = m.raid_day;

COMMENT ON COLUMN v_readiness_daily.mig31k_threat_minutes IS
  'Середня тривалість пари «зліт -> найближчий відбій» у межах 12 годин. '
  'NULL означає, що жоден зліт доби не отримав відбою — це не нуль.';
COMMENT ON COLUMN v_readiness_daily.mig31k_unresolved IS
  'Скільки зльотів доби лишились без відбою. Росте, коли канал змінює '
  'формулювання — дешевий детектор тихої деградації парсера.';

-- v_daily_features відтворюється без змін (залежала лише від імен колонок)
CREATE VIEW v_daily_features AS
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
    COALESCE(l.attacked_kyiv, false)    AS y_attacked,
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
  'Ознаки з суфіксом _prev — усе, що відоме до відсічки 12:00. Колонки y_* — цільові. '
  'УВАГА: night_* тут ФАКТИЧНА погода за вікно прогнозу, тобто витік. У продакшн-'
  'конфігурації (ml/final.py) блок погоди вимкнено; вмикати після накопичення '
  'прогнозних зрізів weather_forecast з issued_at < 12:00.';

--------------------------------------------------------------------------------
-- v_prediction_scores: доба нальоту закінчується о 12:00, а не опівночі
--
-- Було `raid_day < сьогоднішня київська ДАТА`. З 00:00 до 12:00 це пропускало
-- добу, чиє вікно ще відкрите, і оцінювало прогноз проти недорахованого факту —
-- завжди на користь моделі, бо тривоги й треки ще не всі зібрані.
--------------------------------------------------------------------------------
CREATE VIEW v_prediction_scores AS
WITH last_pred AS (
    SELECT DISTINCT ON (raid_day, target, horizon)
           raid_day, target, horizon, p, issued_at, model
    FROM predictions
    ORDER BY raid_day, target, horizon, issued_at DESC
),
fact AS (
    SELECT raid_day,
           y_attacked                                            AS attacked,
           y_alert_minutes >= 30                                 AS alert30,
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
FROM last_pred lp
JOIN fact f ON f.raid_day = lp.raid_day
WHERE lp.raid_day < raid_day(now());

COMMENT ON VIEW v_prediction_scores IS
  'Останній прогноз на добу для кожного горизонту. Доба, що триває, не '
  'оцінюється: межа — raid_day(now()), тобто 12:00, а не опівніч.';
