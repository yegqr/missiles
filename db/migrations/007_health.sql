-- 007_health: самодіагностика конвеєра
--
-- Тиха зупинка парсера гірша за гучну помилку: база виглядає живою, просто
-- перестає доповнюватися. Тому кожен потік має явний строк придатності,
-- і v_health каже, які з них протухли.

CREATE TABLE ingest_expectations (
    source        text PRIMARY KEY,
    max_age       interval NOT NULL,
    description   text
);
INSERT INTO ingest_expectations (source, max_age, description) VALUES
  ('kyiv_digital',       interval '20 minutes', 'тривоги м. Київ, реєстр КМДА'),
  ('tg:air_alert_ua',    interval '20 minutes', 'нові повідомлення каналу'),
  ('tg_parse',           interval '2 hours',    'розбір каналу в тривоги'),
  ('open_meteo_recent',  interval '3 hours',    'оперативна погода'),
  ('open_meteo_forecast',interval '3 hours',    'прогноз погоди'),
  ('open_meteo_archive', interval '30 hours',   'реаналіз ERA5');

CREATE VIEW v_health AS
SELECT
    e.source,
    e.description,
    last.finished_at                         AS остання_вдала,
    now() - last.finished_at                 AS давність,
    e.max_age                                AS дозволено,
    CASE
        WHEN last.finished_at IS NULL                  THEN 'ніколи не запускався'
        WHEN now() - last.finished_at > e.max_age      THEN 'ПРОТУХ'
        ELSE 'ok'
    END                                      AS стан,
    fail.n                                   AS невдач_за_добу
FROM ingest_expectations e
LEFT JOIN LATERAL (
    SELECT r.finished_at FROM ingest_runs r
    WHERE r.source = e.source AND r.status = 'ok'
    ORDER BY r.finished_at DESC LIMIT 1
) last ON true
LEFT JOIN LATERAL (
    SELECT count(*) AS n FROM ingest_runs r
    WHERE r.source = e.source AND r.status = 'error'
      AND r.started_at > now() - interval '24 hours'
) fail ON true;

COMMENT ON VIEW v_health IS 'Стан кожного потоку інжесту. Рядок «ПРОТУХ» = джерело мовчить довше дозволеного.';

-- Скільки часу минуло від останньої відомої події по кожному регіону:
-- окрема перевірка, бо джерело може відповідати, але віддавати старе.
CREATE VIEW v_freshness AS
SELECT r.code AS region_code,
       max(a.started_at)            AS остання_тривога,
       now() - max(a.updated_at)    AS давність_запису
FROM alerts a JOIN regions r ON r.id = a.region_id
GROUP BY r.code;
