-- 013_parse_state: щоб парсери не молотили вхолосту
--
-- Розбір каналу — це повний перерозбір: старі рядки джерела видаляються і
-- пишуться заново. Так задумано, бо правила розбору змінюються і результат
-- має бути відтворюваним з нуля. Але ганяти 76 тисяч повідомлень кожні
-- 15 хвилин, коли нових немає, немає сенсу.
--
-- Тому кожен парсер запам'ятовує, до якого msg_id він дійшов, і мовчки
-- пропускає захід, якщо канал не виріс.

CREATE TABLE parse_state (
    parser        text PRIMARY KEY,
    channel       text,
    last_msg_id   bigint,
    last_run_at   timestamptz NOT NULL DEFAULT now(),
    rows_written  integer
);

INSERT INTO ingest_expectations (source, max_age, description) VALUES
  ('kpszsu_parse',    interval '2 hours', 'зведення ПС і треки на Київ'),
  ('readiness_parse', interval '2 hours', 'зльоти носіїв зброї'),
  ('tg:kpszsu',       interval '2 hours', 'нові повідомлення каналу ПС'),
  ('calendar',        interval '40 days', 'календар свят і тривалості ночі');
