-- 006_parts_fix: пріоритет джерел рахуємо на рівні КАНОНІЧНОГО регіону
--
-- Було: покриття джерела бралося по region_id як він є в alerts. Через це
-- по Київській області офіційні дані «закінчувалися» 04.11.2025 (перехід на
-- районні оголошення), і волонтерський ряд протікав аж у 2026 рік, змішуючись
-- із районними інтервалами.
-- Стало: спершу піднімаємо районні тривоги на рівень області, і лише потім
-- рахуємо, доки дотягується кожне джерело. Районний ряд — це продовження
-- обласного, тому волонтерський більше нікуди не пролазить.

CREATE OR REPLACE VIEW v_alert_parts AS
WITH contrib AS (
    -- (1) власні тривоги регіону
    SELECT a.region_id AS canon_region_id, a.region_id AS src_region_id,
           a.started_at, a.finished_at, a.source, 'own'::text AS part
    FROM alerts a
    UNION ALL
    -- (2) районні тривоги як внесок в обласний ряд
    SELECT r.parent_id, a.region_id, a.started_at, a.finished_at, a.source, 'raion'
    FROM alerts a
    JOIN regions r ON r.id = a.region_id
    WHERE r.level = 'raion' AND r.parent_id IS NOT NULL
),
coverage AS (
    SELECT c.canon_region_id, c.source, s.priority,
           MIN(c.started_at) AS from_ts, MAX(c.started_at) AS to_ts
    FROM contrib c JOIN alert_sources s ON s.code = c.source
    GROUP BY c.canon_region_id, c.source, s.priority
)
SELECT c.canon_region_id, c.src_region_id, c.started_at, c.finished_at, c.source, c.part
FROM contrib c
JOIN coverage cv ON cv.canon_region_id = c.canon_region_id AND cv.source = c.source
WHERE NOT EXISTS (
    SELECT 1 FROM coverage h
    WHERE h.canon_region_id = c.canon_region_id
      AND h.priority < cv.priority
      AND c.started_at BETWEEN h.from_ts AND h.to_ts
);
