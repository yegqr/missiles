-- 011: випереджувальні сигнали носіїв + календар
--
-- ДВІ РІЗНІ РЕЧІ, ОБИДВІ — ОЗНАКИ, НЕ ЛЕЙБЛИ.
--
-- readiness_signals: зліт носіїв зброї. Єдине, що дає фору в години:
--   МіГ-31К (носій «Кинджала») — від зльоту до пуску десятки хвилин;
--   Ту-95 / Ту-160 — від зльоту з Енгельса чи Оленьї до пуску 8–12 годин;
--   надводні й підводні носії «Калібр» у Чорному морі.
-- Канал ПС дає зліт І відбій, тобто не лише подію, а тривалість загрози.
--
-- calendar_days: свята. Українські — бо демонстративні удари прив'язують до
-- дат; російські — бо до них прив'язують «перемоги». Обидва набори окремо:
-- змішувати їх в одну колонку означає втратити напрямок ефекту.

CREATE TABLE readiness_signals (
    id          bigserial PRIMARY KEY,
    ts          timestamptz NOT NULL,
    signal_type text        NOT NULL,
    platform    text,                    -- mig31k, tu95, tu160, kalibr_ship
    airfield    text,                    -- Саваслейка, Приволзький, Оленья, Енгельс
    is_standdown boolean    NOT NULL DEFAULT false,
    source      text        NOT NULL,
    msg_id      bigint,
    evidence    text,
    raid_day    date GENERATED ALWAYS AS (raid_day(ts)) STORED,
    UNIQUE (source, msg_id, signal_type)
);
CREATE INDEX readiness_day  ON readiness_signals (raid_day);
CREATE INDEX readiness_time ON readiness_signals (ts);

COMMENT ON COLUMN readiness_signals.is_standdown IS
  'true = «відбій загрози по МіГ-31К». Пара зліт+відбій дає тривалість загрози, '
  'а це змістовніша величина, ніж сам факт зльоту.';

--------------------------------------------------------------------------------
-- Календар
--------------------------------------------------------------------------------

CREATE TABLE calendar_days (
    day           date PRIMARY KEY,
    dow           smallint NOT NULL,     -- 1 = понеділок
    month         smallint NOT NULL,
    -- свята
    holiday_ua    text,
    holiday_ua_w  smallint,              -- вага 1..3
    holiday_ru    text,
    holiday_ru_w  smallint,
    -- астрономія: вікно для нічної атаки
    night_hours   real,                  -- тривалість темного часу
    -- опалювальний сезон: удари по енергетиці мають виражену сезонність
    heating_season boolean NOT NULL DEFAULT false
);

COMMENT ON COLUMN calendar_days.holiday_ua_w IS
  '3 — Незалежності, Різдво, Великдень, Новий рік; 2 — Конституції, Державності, '
  'Захисників, Соборності; 1 — решта пам''ятних дат';
COMMENT ON COLUMN calendar_days.night_hours IS
  'Темний час доби. Взимку вікно для нічної атаки майже вдвічі довше, ніж улітку.';
