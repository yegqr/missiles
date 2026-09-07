-- 015_horizon: два горизонти прогнозу
--
-- «Сьогодні» — вікно, що починається о 12:00 сьогодні (ознаки зі зсувом 1).
-- «Завтра» — наступне вікно (зсув 2): на момент відсічки доба d-1 ще триває,
-- тому останнє повністю відоме — це d-2. Плутанина між ними коштує витоку,
-- який виглядає як несподівано хороша модель.

ALTER TABLE predictions ADD COLUMN horizon smallint NOT NULL DEFAULT 1
    CHECK (horizon IN (1, 2));

COMMENT ON COLUMN predictions.horizon IS
  '1 — вікно, що вже почалось (12:00 сьогодні); 2 — наступне вікно (завтра). '
  'Обидва прогнози на ту саму raid_day видані в різні дні й різними моделями.';

ALTER TABLE predictions DROP CONSTRAINT predictions_pkey;
ALTER TABLE predictions ADD PRIMARY KEY (raid_day, target, horizon, issued_at);

DROP VIEW IF EXISTS v_prediction_scores;
CREATE VIEW v_prediction_scores AS
WITH last_pred AS (
    SELECT DISTINCT ON (raid_day, target, horizon)
           raid_day, target, horizon, p, issued_at, model
    FROM predictions
    ORDER BY raid_day, target, horizon, issued_at DESC
)
SELECT
    lp.raid_day, lp.target, lp.horizon, lp.p, lp.issued_at, lp.model,
    CASE lp.target
        WHEN 'attacked' THEN f.y_attacked
        WHEN 'alert30'  THEN f.y_alert_minutes >= 30
        WHEN 'massive'  THEN f.y_drone_tracks >= 11 OR f.y_missile_tracks >= 4
    END                                    AS факт,
    (lp.p - (CASE lp.target
        WHEN 'attacked' THEN f.y_attacked::int
        WHEN 'alert30'  THEN (f.y_alert_minutes >= 30)::int
        WHEN 'massive'  THEN (f.y_drone_tracks >= 11 OR f.y_missile_tracks >= 4)::int
    END)) ^ 2                              AS brier
FROM last_pred lp
JOIN v_daily_features f ON f.raid_day = lp.raid_day
WHERE lp.raid_day < (now() AT TIME ZONE 'Europe/Kyiv')::date;

COMMENT ON VIEW v_prediction_scores IS
  'Останній прогноз на добу для кожного горизонту. Доба, що триває, не оцінюється.';
