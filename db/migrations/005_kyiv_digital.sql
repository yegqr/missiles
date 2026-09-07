-- 005_kyiv_digital: первинне джерело по місту Києву
--
-- https://kyiv.digital/open-api/air-alert/history — реєстр КМДА («Київ Цифровий»),
-- опублікований на Порталі даних Києва. Без токена, XML.
-- Віддає ВСЮ історію змін стану з 25.02.2022 07:19 і поточний стан наживо,
-- плюс поле causes (drone / ...) — тип загрози, якого немає в жодному датасеті.
--
-- Час у джерелі — київський локальний, без позначки зони. Перевірено збігом
-- до секунди з нашим рядом: 2026-09-05T01:58:53 місцевого = 2026-09-04 22:58:53 UTC.
--
-- Для м. Києва це джерело витісняє все інше (пріоритет 0).
-- По області такого реєстру немає — там первинним лишається @air_alert_ua.

ALTER TABLE alerts DROP CONSTRAINT alerts_source_check;
ALTER TABLE alerts ADD CONSTRAINT alerts_source_check
    CHECK (source IN ('official','volunteer','alerts_in_ua','tg_air_alert_ua','kyiv_digital'));

INSERT INTO alert_sources (code, priority, note) VALUES
  ('kyiv_digital', 0, 'реєстр КМДА «Київ Цифровий», офіційний, тільки м. Київ');

-- Тип загрози з поля causes
ALTER TABLE alerts ADD COLUMN causes text[];
