-- 012_features: добові ознаки з дотриманням відсічки
--
-- Відсічка — 12:00 київського часу доби d, і саме о 12:00 починається
-- доба нальоту d. Отже все, що сталося до відсічки, — це рівно попередня
-- доба нальоту (d-1). Звідси просте правило: ЛАГОВАНА ознака = значення
-- за raid_day (d-1). Ніякої окремої арифметики годин не треба.
--
-- Колонки без суфікса — те, що сталося ВСЕРЕДИНІ вікна прогнозу. Вони
-- НЕ ознаки: у модель їх подавати не можна, вони для аналізу й для
-- поточного оцінювання ситуації в реальному часі.
-- Ознаки — тільки колонки з суфіксом _prev.

CREATE VIEW v_readiness_daily AS
SELECT
    raid_day,
    count(*) FILTER (WHERE platform='mig31k' AND NOT is_standdown) AS mig31k_takeoffs,
    count(*) FILTER (WHERE platform IN ('tu95','tu160'))           AS strategic_takeoffs,
    count(*) FILTER (WHERE platform='kalibr_ship')                 AS kalibr_signals,
    -- від першого зльоту МіГ-31К до останнього відбою: тривалість загрози
    EXTRACT(epoch FROM (
        max(ts) FILTER (WHERE platform='mig31k' AND is_standdown)
      - min(ts) FILTER (WHERE platform='mig31k' AND NOT is_standdown)))/60.0
                                                                   AS mig31k_threat_minutes
FROM readiness_signals
GROUP BY raid_day;

CREATE VIEW v_daily_features AS
SELECT
    c.day AS raid_day,
    c.dow, c.month, c.night_hours, c.heating_season,
    c.holiday_ua, COALESCE(c.holiday_ua_w, 0) AS holiday_ua_w,
    c.holiday_ru, COALESCE(c.holiday_ru_w, 0) AS holiday_ru_w,

    -- ОЗНАКИ: усе відоме до 12:00, тобто за попередню добу нальоту
    COALESCE(pl.alerts_count, 0)        AS alerts_prev,
    COALESCE(pl.alert_minutes, 0)       AS alert_minutes_prev,
    COALESCE(pl.drone_tracks_kyiv, 0)   AS drone_tracks_prev,
    COALESCE(pl.missile_tracks_kyiv, 0) AS missile_tracks_prev,
    COALESCE(pl.drones_launched_ua, 0)  AS drones_launched_ua_prev,
    COALESCE(pr.mig31k_takeoffs, 0)     AS mig31k_prev,
    COALESCE(pr.strategic_takeoffs, 0)  AS strategic_prev,
    COALESCE(pr.kalibr_signals, 0)      AS kalibr_prev,

    -- прогноз погоди на ніч: валідна ознака, бо о 12:00 вже виданий
    fw.night_cloud_low_avg, fw.night_wind_avg, fw.night_temp_avg,
    fw.night_precip_sum,

    -- ЩО СТАЛОСЯ ВСЕРЕДИНІ ВІКНА — не ознаки, для аналізу
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
  'Ознаки з суфіксом _prev — усе, що відоме до відсічки 12:00. Колонки y_* — '
  'цільові. mig31k_same_window всередині вікна: не ознака, а факт для аналізу.';
