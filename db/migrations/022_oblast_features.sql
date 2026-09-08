-- 022: цілі над областю доходять до навчальної таблиці
--
-- Лейбл лишається міським: attacked_kyiv рахується ТІЛЬКИ з треків міста.
-- Обласні треки стають ознакою — і саме лагованою, як усе інше.

DROP VIEW IF EXISTS v_prediction_scores;
DROP VIEW IF EXISTS v_daily_features;
DROP VIEW IF EXISTS v_daily_labels;

CREATE VIEW v_daily_labels AS
WITH days AS (
    SELECT raid_day FROM attack_observations
    UNION
    SELECT raid_day FROM v_canon_daily WHERE region_code = 'kyiv_city'
),
wide AS (
    SELECT raid_day,
        max(значення) FILTER (WHERE metric='drone_tracks'      AND scope='kyiv')     AS drone_tracks_kyiv,
        max(значення) FILTER (WHERE metric='missile_tracks'    AND scope='kyiv')     AS missile_tracks_kyiv,
        max(значення) FILTER (WHERE metric='drone_tracks'      AND scope='kyiv_obl') AS drone_tracks_obl,
        max(значення) FILTER (WHERE metric='missile_tracks'    AND scope='kyiv_obl') AS missile_tracks_obl,
        max(значення) FILTER (WHERE metric='impacts'           AND scope='kyiv')     AS impacts_kyiv,
        max(значення) FILTER (WHERE metric='killed'            AND scope='kyiv')     AS killed_kyiv,
        max(значення) FILTER (WHERE metric='injured'           AND scope='kyiv')     AS injured_kyiv,
        max(значення) FILTER (WHERE metric='drones_launched'   AND scope='ua')       AS drones_launched_ua,
        max(значення) FILTER (WHERE metric='targets_downed'    AND scope='ua')       AS targets_downed_ua,
        max(значення) FILTER (WHERE metric='missiles_launched' AND scope='ua')       AS missiles_launched_ua,
        max(значення) FILTER (WHERE metric='impact_locations'  AND scope='ua')       AS impact_locations_ua,
        bool_or(суперечність)                                                        AS є_суперечність
    FROM v_label_counts GROUP BY raid_day
)
SELECT
    d.raid_day,
    COALESCE(a.attacked, w.drone_tracks_kyiv > 0)        AS attacked_kyiv,
    COALESCE(a.впевненість, 'немає джерел')              AS attacked_confidence,
    w.drone_tracks_kyiv, w.missile_tracks_kyiv,
    w.drone_tracks_obl, w.missile_tracks_obl,
    w.impacts_kyiv, w.killed_kyiv, w.injured_kyiv,
    w.drones_launched_ua, w.targets_downed_ua,
    w.missiles_launched_ua, w.impact_locations_ua,
    COALESCE(w.є_суперечність, false)                    AS є_суперечність,
    COALESCE(al.alerts_count, 0)  AS alerts_count,
    COALESCE(al.total_minutes, 0) AS alert_minutes,
    COALESCE(al.night_minutes, 0) AS alert_night_minutes
FROM days d
LEFT JOIN v_label_attacked a ON a.raid_day = d.raid_day
LEFT JOIN wide w             ON w.raid_day = d.raid_day
LEFT JOIN v_canon_daily al   ON al.raid_day = d.raid_day AND al.region_code = 'kyiv_city';

COMMENT ON VIEW v_daily_labels IS
  'attacked_kyiv = NULL означає «жодне джерело нічого не стверджувало». '
  'Треки міста й області — різні колонки: лейбл будується ТІЛЬКИ з міських.';

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
    COALESCE(pl.drone_tracks_obl, 0)    AS drone_tracks_obl_prev,
    COALESCE(pl.missile_tracks_obl, 0)  AS missile_tracks_obl_prev,
    COALESCE(pl.drones_launched_ua, 0)  AS drones_launched_ua_prev,
    COALESCE(pr.mig31k_takeoffs, 0)     AS mig31k_prev,
    COALESCE(pr.strategic_takeoffs, 0)  AS strategic_prev,
    COALESCE(pr.kalibr_signals, 0)      AS kalibr_prev,
    fw.night_cloud_low_avg, fw.night_wind_avg, fw.night_temp_avg, fw.night_precip_sum,
    l.attacked_kyiv                     AS y_attacked,
    COALESCE(l.drone_tracks_kyiv, 0)    AS y_drone_tracks,
    COALESCE(l.missile_tracks_kyiv, 0)  AS y_missile_tracks,
    COALESCE(l.drone_tracks_obl, 0)     AS y_drone_tracks_obl,
    COALESCE(l.alert_minutes, 0)        AS y_alert_minutes,
    COALESCE(rd.mig31k_takeoffs, 0)     AS mig31k_same_window
FROM calendar_days c
LEFT JOIN v_daily_labels     l  ON l.raid_day  = c.day
LEFT JOIN v_daily_labels     pl ON pl.raid_day = c.day - 1
LEFT JOIN v_readiness_daily  pr ON pr.raid_day = c.day - 1
LEFT JOIN v_readiness_daily  rd ON rd.raid_day = c.day
LEFT JOIN v_weather_daily    fw ON fw.raid_day = c.day AND fw.location_code = 'kyiv'
WHERE c.day >= '2022-02-24';

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
