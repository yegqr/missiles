-- 016_massive: означення масованої атаки через тривалість тривог
--
-- Кількість треків — це кількість повідомлень каналу, і вона росте разом із
-- його балакучістю: q90 у добу атаки 5 (2024), 5 (2025), 9 (2026), максимум
-- 10 -> 21 -> 38. Поріг, знятий з одного року, наступного означає вже інше.
-- Хвилини тривог надходять із реєстру КМДА — тракту, незалежного від каналу.

DROP VIEW IF EXISTS v_prediction_scores;
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
WHERE lp.raid_day < (now() AT TIME ZONE 'Europe/Kyiv')::date;
