-- 004_telegram: власний парсинг первинного джерела
--
-- Первинне джерело офіційних тривог — канал @air_alert_ua (система оповіщення).
-- Публічний веб-перегляд t.me/s/<канал> віддає всю історію з повідомлення №1
-- (14.03.2022) без токена й без Telegram-акаунта, з точним UTC-часом.
-- Готові датасети більше не потрібні: ми тримаємо сирі повідомлення в себе
-- і можемо перепарсити їх будь-коли, не перекачуючи канал.

-- Сирі повідомлення. Зберігаємо ВСІ, не тільки київські: у тому ж каналі
-- ідуть повідомлення про тип загрози (БпЛА, балістика, авіація), а це пряма
-- підказка про засоби ураження.
CREATE TABLE tg_messages (
    channel     text        NOT NULL,
    msg_id      bigint      NOT NULL,
    posted_at   timestamptz NOT NULL,
    text        text        NOT NULL,
    fetched_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (channel, msg_id)
);
CREATE INDEX tg_messages_time ON tg_messages (channel, posted_at);

-- Прогрес обходу каналу: щоб не перечитувати вже завантажене
CREATE TABLE tg_scan_state (
    channel      text PRIMARY KEY,
    min_msg_id   bigint,
    max_msg_id   bigint,
    updated_at   timestamptz NOT NULL DEFAULT now()
);

-- Типи загроз із того ж каналу (БпЛА / балістика / авіація)
CREATE TABLE threat_events (
    id          bigserial PRIMARY KEY,
    region_id   smallint    NOT NULL REFERENCES regions(id),
    ts          timestamptz NOT NULL,
    threat_type text        NOT NULL,
    msg_id      bigint,
    UNIQUE (region_id, ts, threat_type)
);
CREATE INDEX threat_events_time ON threat_events (ts);

-- Дозволяємо нове джерело
ALTER TABLE alerts DROP CONSTRAINT alerts_source_check;
ALTER TABLE alerts ADD CONSTRAINT alerts_source_check
    CHECK (source IN ('official','volunteer','alerts_in_ua','tg_air_alert_ua'));

--------------------------------------------------------------------------------
-- Пріоритет джерел у канонічному ряді
--------------------------------------------------------------------------------
CREATE TABLE alert_sources (
    code     text PRIMARY KEY,
    priority smallint NOT NULL,   -- менше = краще
    note     text
);
INSERT INTO alert_sources (code, priority, note) VALUES
  ('tg_air_alert_ua', 1, 'наш парсер каналу @air_alert_ua — первинне джерело'),
  ('alerts_in_ua',    2, 'лайв-API, якщо є токен'),
  ('official',        3, 'готовий датасет Vadimkin, офіційний канал'),
  ('volunteer',       4, 'готовий датасет Vadimkin, eTryvoga; єдине джерело до 15.03.2022');

-- Джерело нижчого пріоритету бере слово лише там, куди не дотягується вище:
-- саме так волонтерські дані закривають 25.02–15.03.2022, і саме так наш
-- парсер витіснить готовий датасет, щойно відпрацює.
CREATE OR REPLACE VIEW v_alert_parts AS
WITH coverage AS (
    SELECT a.region_id, a.source, s.priority,
           MIN(a.started_at) AS from_ts, MAX(a.started_at) AS to_ts
    FROM alerts a JOIN alert_sources s ON s.code = a.source
    GROUP BY a.region_id, a.source, s.priority
),
usable AS (
    SELECT a.id, a.region_id, a.started_at, a.finished_at, a.source
    FROM alerts a
    JOIN coverage c ON c.region_id = a.region_id AND c.source = a.source
    WHERE NOT EXISTS (
        SELECT 1 FROM coverage h
        WHERE h.region_id = a.region_id
          AND h.priority < c.priority
          AND a.started_at BETWEEN h.from_ts AND h.to_ts
    )
)
SELECT u.region_id AS canon_region_id, u.region_id AS src_region_id,
       u.started_at, u.finished_at, u.source, 'own'::text AS part
FROM usable u
JOIN regions r ON r.id = u.region_id
WHERE r.level <> 'raion'

UNION ALL

-- районні тривоги піднімаємо на рівень області: після липня 2025 обласних
-- оголошень немає, і обласний ряд існує тільки як об'єднання районних
SELECT r.parent_id, u.region_id, u.started_at, u.finished_at, u.source, 'raion'
FROM usable u
JOIN regions r ON r.id = u.region_id
WHERE r.level = 'raion' AND r.parent_id IS NOT NULL

UNION ALL

-- сам район теж лишається окремим канонічним рядом
SELECT u.region_id, u.region_id, u.started_at, u.finished_at, u.source, 'own'
FROM usable u
JOIN regions r ON r.id = u.region_id
WHERE r.level = 'raion';
