-- 014_predictions: збереження прогнозів
--
-- Прогноз пишеться в базу, а не тільки друкується, з однієї причини: без
-- історії виданих прогнозів неможливо виміряти, як модель поводиться в житті.
-- Бектест на минулому і реальна робота — різні речі, і розходження між ними
-- видно тільки якщо кожен прогноз збережено з часом видачі.

CREATE TABLE predictions (
    raid_day    date        NOT NULL,
    target      text        NOT NULL CHECK (target IN ('attacked','alert30','massive')),
    issued_at   timestamptz NOT NULL DEFAULT now(),
    p           numeric     NOT NULL CHECK (p >= 0 AND p <= 1),
    model       text        NOT NULL,     -- конфігурація, напр. median_top5
    members     jsonb,                    -- які моделі увійшли і їх CV-оцінки
    prior_shift boolean     NOT NULL DEFAULT false,
    n_train     integer,
    PRIMARY KEY (raid_day, target, issued_at)
);

COMMENT ON TABLE predictions IS
  'Один рядок = один виданий прогноз. Рядки НЕ перезаписуються: перепрогноз '
  'тієї самої доби додає новий issued_at, і видно, як оцінка змінювалась.';
COMMENT ON COLUMN predictions.members IS
  'Склад ансамблю на момент видачі. Склад міняється з кожним дотренуванням, '
  'бо моделі відбираються за CV заново — без цього поля прогноз невідтворюваний.';

CREATE INDEX predictions_day ON predictions (raid_day, target);

--------------------------------------------------------------------------------
-- Прогноз проти факту: єдине джерело правди про якість у реальній роботі
--------------------------------------------------------------------------------
CREATE VIEW v_prediction_scores AS
WITH last_pred AS (
    SELECT DISTINCT ON (raid_day, target) raid_day, target, p, issued_at, model
    FROM predictions
    ORDER BY raid_day, target, issued_at DESC
)
SELECT
    lp.raid_day, lp.target, lp.p, lp.issued_at, lp.model,
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
  'Береться ОСТАННІЙ прогноз на добу. Доба, що ще триває, не оцінюється.';
