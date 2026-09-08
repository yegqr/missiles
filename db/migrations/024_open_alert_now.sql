-- 024: відкрита тривога триває ДО ЗАРАЗ, а не 24 години наперед.
--
-- У 020 «безсмертні» тривоги обрізали 24 годинами: LEAST(COALESCE(finished_at,
-- started_at + 24h), started_at + 24h). Для загубленого відбою це правильно,
-- але для тривоги, що ТРИВАЄ ЗАРАЗ, це означало миттєво нарахувати добі 24
-- години вперед. Наслідок видно на 08.09.2026: тривога почалась об 11:00 за
-- Києвом, а доба нальоту вже показувала 1381 хвилину і 480 «нічних» хвилин,
-- яких ще фізично не було. Наступного ранку така доба автоматично ставала
-- «масованою атакою» незалежно від того, що сталося насправді.
--
-- COALESCE(finished_at, now()) нижче за течією не рятував: у v_alert_parts
-- значення вже не NULL, а started_at + 24h.
--
-- Правило: кінець відкритого інтервалу = min(зараз, старт + 24 год).
-- Обидві гарантії лишаються: майбутнє не рахується, несправність джерела
-- не дає тривоги довші за добу.

CREATE OR REPLACE VIEW v_alert_parts AS
WITH contrib AS (
    SELECT a.region_id AS canon_region_id, a.region_id AS src_region_id,
           a.started_at,
           LEAST(COALESCE(a.finished_at, now()),
                 a.started_at + interval '24 hours') AS finished_at,
           a.finished_at IS NULL AS is_open,
           a.source, 'own'::text AS part
    FROM alerts a
    UNION ALL
    SELECT r.parent_id, a.region_id, a.started_at,
           LEAST(COALESCE(a.finished_at, now()),
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
      AND h.started_at < p.finished_at
      AND p.started_at < h.finished_at
);

COMMENT ON VIEW v_alert_parts IS
  'Внески в канонічний ряд. Джерело нижчого пріоритету відкидається лише там, '
  'де реально перекривається з вищим. Відкритий інтервал закінчується '
  'min(зараз, старт + 24 год): майбутні хвилини не нараховуються, а загублений '
  'відбій не дає тривоги, довшої за добу.';
