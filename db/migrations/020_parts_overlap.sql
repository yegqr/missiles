-- 020: пріоритет джерел вирішується ПЕРЕКРИТТЯМ, а не суцільним відрізком
--
-- Було: покриття джерела = MIN(started_at)..MAX(started_at), один суцільний
-- відрізок без дірок усередині. kyiv_digital має пріоритет 0 і покриття
-- 25.02.2022 -> сьогодні, тому будь-яка тривога з іншого джерела по місту
-- відкидалась — навіть там, де в kyiv_digital події просто НЕМАЄ.
-- Наслідок: 11 тривог по місту, підтверджених трьома незалежними джерелами,
-- випадали з канонічного ряду. Приклад — 25.03.2022 13:34-15:33, яку фіксують
-- official, tg_air_alert_ua і volunteer одночасно: у ряді на її місці дірка,
-- і доба недорахувала 118 хвилин.
--
-- Стало: внесок нижчого пріоритету відкидається лише тоді, коли він реально
-- ПЕРЕКРИВАЄТЬСЯ з інтервалом вищого. Дублікати так само не подвоюються (їх
-- зливає gaps-and-islands нижче за течією), а справжні дірки закриваються.
--
-- Заразом: «безсмертні» тривоги. Загублений відбій давав інтервал на 4.7 доби
-- (Бровари 29.08 -> 02.09.2026), і область стояла 1440 хв/добу чотири доби
-- поспіль. Відкритий інтервал тепер обмежений 24 годинами: далі це вже не
-- тривога, а несправність джерела, і рахувати її як тривогу неправильно.

CREATE OR REPLACE VIEW v_alert_parts AS
WITH contrib AS (
    SELECT a.region_id AS canon_region_id, a.region_id AS src_region_id,
           a.started_at,
           LEAST(COALESCE(a.finished_at, a.started_at + interval '24 hours'),
                 a.started_at + interval '24 hours') AS finished_at,
           a.finished_at IS NULL AS is_open,
           a.source, 'own'::text AS part
    FROM alerts a
    UNION ALL
    SELECT r.parent_id, a.region_id, a.started_at,
           LEAST(COALESCE(a.finished_at, a.started_at + interval '24 hours'),
                 a.started_at + interval '24 hours'),
           a.finished_at IS NULL,
           a.source, 'raion'
    FROM alerts a
    JOIN regions r ON r.id = a.region_id
    WHERE r.level = 'raion' AND r.parent_id IS NOT NULL
),
pri AS (
    SELECT c.*, s.priority FROM contrib c JOIN alert_sources s ON s.code = c.source
)
SELECT p.canon_region_id, p.src_region_id, p.started_at, p.finished_at,
       p.source, p.part
FROM pri p
WHERE NOT EXISTS (
    SELECT 1 FROM pri h
    WHERE h.canon_region_id = p.canon_region_id
      AND h.priority < p.priority
      AND h.started_at < p.finished_at          -- перекриття інтервалів
      AND p.started_at < h.finished_at
);

COMMENT ON VIEW v_alert_parts IS
  'Внески в канонічний ряд. Джерело нижчого пріоритету відкидається лише там, '
  'де реально перекривається з вищим — а не на всьому його часовому відрізку. '
  'Відкриті інтервали обрізані 24 годинами: довше — це вже несправність '
  'джерела, а не тривога.';
