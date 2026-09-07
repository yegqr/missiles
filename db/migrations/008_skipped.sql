-- 008_skipped: окремий статус для свідомо пропущеного кроку
--
-- Розбір каналу не може працювати, доки не завершився обхід історії.
-- Це не помилка і не мовчання: крок відпрацював і свідомо нічого не зробив.
-- Позначати його як 'ok' було б неправдою, як 'error' — панікою.

ALTER TABLE ingest_runs DROP CONSTRAINT ingest_runs_status_check;
ALTER TABLE ingest_runs ADD CONSTRAINT ingest_runs_status_check
    CHECK (status IN ('running','ok','error','skipped'));

CREATE OR REPLACE VIEW v_health AS
SELECT
    e.source,
    e.description,
    last.finished_at                         AS остання_вдала,
    now() - last.finished_at                 AS давність,
    e.max_age                                AS дозволено,
    CASE
        WHEN last.finished_at IS NULL             THEN 'ніколи не запускався'
        WHEN now() - last.finished_at > e.max_age THEN 'ПРОТУХ'
        WHEN last.status = 'skipped'              THEN 'пропущено: ' || COALESCE(last.note, '')
        ELSE 'ok'
    END                                      AS стан,
    fail.n                                   AS невдач_за_добу
FROM ingest_expectations e
LEFT JOIN LATERAL (
    SELECT r.finished_at, r.status, r.params->>'reason' AS note
    FROM ingest_runs r
    WHERE r.source = e.source AND r.status IN ('ok','skipped')
    ORDER BY r.finished_at DESC LIMIT 1
) last ON true
LEFT JOIN LATERAL (
    SELECT count(*) AS n FROM ingest_runs r
    WHERE r.source = e.source AND r.status = 'error'
      AND r.started_at > now() - interval '24 hours'
) fail ON true;
