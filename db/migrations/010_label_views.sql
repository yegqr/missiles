-- 010_label_views: узгодження спостережень у лейбли
--
-- Правило крос-валідації: лейбл формують ТІЛЬКИ джерела tier='official'
-- (плюс 'dataset' для звірки чисел). Моніторингові канали не голосують —
-- вони дають ознаки. Впевненість = чи зійшлися незалежні джерела.

--------------------------------------------------------------------------------
-- Бінарний лейбл: чи був удар по Києву цієї доби нальоту
--------------------------------------------------------------------------------
CREATE VIEW v_label_attacked AS
WITH votes AS (
    SELECT raid_day, source, max(value) AS v
    FROM attack_observations
    WHERE metric = 'attacked' AND scope = 'kyiv' AND tier = 'official'
    GROUP BY raid_day, source
)
SELECT
    raid_day,
    count(*)                                    AS джерел,
    count(*) FILTER (WHERE v = 1)               AS за,
    count(*) FILTER (WHERE v = 0)               AS проти,
    (count(*) FILTER (WHERE v = 1) > count(*) FILTER (WHERE v = 0)) AS attacked,
    CASE
        WHEN count(*) FILTER (WHERE v = 1) = count(*) THEN 'повна згода'
        WHEN count(*) FILTER (WHERE v = 0) = count(*) THEN 'повна згода'
        ELSE 'РОЗБІЖНІСТЬ'
    END                                         AS впевненість
FROM votes
GROUP BY raid_day;

--------------------------------------------------------------------------------
-- Числа: медіана по джерелах, розкид і позначка суперечності
--------------------------------------------------------------------------------
CREATE VIEW v_label_counts AS
SELECT
    raid_day, metric, scope,
    count(*)                                           AS джерел,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY value) AS значення,
    min(value) AS мін, max(value) AS макс,
    -- розкид понад 10% між джерелами = привід глянути очима
    (max(value) - min(value)) > 0.1 * NULLIF(max(value), 0) AS суперечність
FROM attack_observations
WHERE tier IN ('official','dataset') AND value IS NOT NULL
GROUP BY raid_day, metric, scope;

--------------------------------------------------------------------------------
-- Підсумкова таблиця для навчання
--
-- Колонки з суфіксом _kyiv і _ua — це РІЗНІ ВЕЛИЧИНИ. _ua точні, але по країні;
-- _kyiv по місту, але це кількість спостережень, а не бортів. Не складати.
--------------------------------------------------------------------------------
CREATE VIEW v_daily_labels AS
WITH days AS (
    SELECT raid_day FROM attack_observations
    UNION
    SELECT raid_day FROM v_canon_daily WHERE region_code = 'kyiv_city'
),
wide AS (
    SELECT raid_day,
        max(значення) FILTER (WHERE metric='drone_tracks'      AND scope='kyiv') AS drone_tracks_kyiv,
        max(значення) FILTER (WHERE metric='missile_tracks'    AND scope='kyiv') AS missile_tracks_kyiv,
        max(значення) FILTER (WHERE metric='impacts'           AND scope='kyiv') AS impacts_kyiv,
        max(значення) FILTER (WHERE metric='killed'            AND scope='kyiv') AS killed_kyiv,
        max(значення) FILTER (WHERE metric='injured'           AND scope='kyiv') AS injured_kyiv,
        max(значення) FILTER (WHERE metric='drones_launched'   AND scope='ua')   AS drones_launched_ua,
        max(значення) FILTER (WHERE metric='drones_downed'     AND scope='ua')   AS drones_downed_ua,
        max(значення) FILTER (WHERE metric='missiles_launched' AND scope='ua')   AS missiles_launched_ua,
        max(значення) FILTER (WHERE metric='missiles_downed'   AND scope='ua')   AS missiles_downed_ua,
        bool_or(суперечність)                                                    AS є_суперечність
    FROM v_label_counts
    GROUP BY raid_day
)
SELECT
    d.raid_day,
    COALESCE(a.attacked, w.drone_tracks_kyiv > 0, false) AS attacked_kyiv,
    COALESCE(a.впевненість, 'немає джерел')              AS attacked_confidence,
    w.drone_tracks_kyiv, w.missile_tracks_kyiv,
    w.impacts_kyiv, w.killed_kyiv, w.injured_kyiv,
    w.drones_launched_ua, w.drones_downed_ua,
    w.missiles_launched_ua, w.missiles_downed_ua,
    COALESCE(w.є_суперечність, false)                    AS є_суперечність,
    -- тривоги беруться з канонічного ряду, тобто з окремого, незалежного тракту
    COALESCE(al.alerts_count, 0)  AS alerts_count,
    COALESCE(al.total_minutes, 0) AS alert_minutes,
    COALESCE(al.night_minutes, 0) AS alert_night_minutes
FROM days d
LEFT JOIN v_label_attacked a ON a.raid_day = d.raid_day
LEFT JOIN wide w             ON w.raid_day = d.raid_day
LEFT JOIN v_canon_daily al   ON al.raid_day = d.raid_day AND al.region_code = 'kyiv_city';

COMMENT ON VIEW v_daily_labels IS
  'Один рядок на добу нальоту. Колонки _kyiv і _ua — різні величини, не складати. '
  'є_суперечність = джерела розійшлися, рядок треба дивитися очима перед навчанням.';
