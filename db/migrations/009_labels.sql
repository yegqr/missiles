-- 009_labels: спостереження -> узгоджені лейбли для ML
--
-- ГОЛОВНЕ, ЩО ТРЕБА ЗНАТИ ПРО ЦІ ДАНІ
--
-- Точної кількості дронів і ракет саме по Києву не публікує НІХТО. Перевірено:
--   * Повітряні Сили дають лише загальнонаціональні числа за ніч
--     («атакував 92 БпЛА, збито 71») — розбивки по містах у зведеннях немає;
--   * пошук «у Києві збито» по каналу ПС дає нуль результатів;
--   * КМВА і мер повідомляють наслідки (влучання, поранені), а не кількість цілей;
--   * ACLED рахує ПОДІЇ (удар був / не був), а не боєприпаси.
--
-- Тому вигадувати колонку «ракет на Київ = 20» не можна: модель, навчена на
-- вигаданому числі, буде гіршою за модель, навчену на чесній порядковій шкалі.
-- Замість цього тримаємо ТРИ РІЗНІ ВЕЛИЧИНИ і ніколи їх не змішуємо:
--
--   scope='kyiv' + метрики *_tracks — скільки разів джерело зафіксувало ціль
--       курсом на Київ. Це спостереження, не кількість бортів: одне
--       повідомлення може означати «група БпЛА». Чесна назва — «треки».
--   scope='ua'   — точні числа за ніч по країні зі зведення ПС. Точні, але не київські.
--   scope='kyiv' + наслідки — влучання, загиблі, поранені по місту.
--
-- Оцінку «скільки з національних N припало на Київ» можна рахувати як частку
-- треків, але тільки як ЯВНО позначену оцінку, ніколи не як факт.

--------------------------------------------------------------------------------
-- Реєстр джерел
--------------------------------------------------------------------------------

CREATE TABLE tg_channels (
    handle      text PRIMARY KEY,          -- без @
    title       text NOT NULL,
    tier        text NOT NULL CHECK (tier IN ('official','monitor','dataset')),
    role        text NOT NULL,             -- що саме з нього беремо
    is_active   boolean NOT NULL DEFAULT true,
    added_at    timestamptz NOT NULL DEFAULT now()
);

COMMENT ON COLUMN tg_channels.tier IS
  'official — держоргани й ПС, лише вони формують лейбли; '
  'monitor — моніторингові канали, тільки ознаки, НІКОЛИ не лейбли; '
  'dataset — зовнішній набір для звірки';

INSERT INTO tg_channels (handle, title, tier, role) VALUES
  ('kpszsu',            'Повітряні Сили ЗСУ',        'official',
   'добові зведення (національні числа) + супровід цілей курсом на Київ'),
  ('air_alert_ua',      'Повітряна тривога',          'official',
   'тривоги по регіонах + тип загрози'),
  ('kyivoda',           'Київська ОВА',               'official',
   'тривоги по районах області, наслідки по області'),
  ('Vitaliy_Klitschko', 'Віталій Кличко',             'official',
   'наслідки по місту: влучання, постраждалі'),
  ('dsns_telegram',     'ДСНС України',               'official',
   'ліквідація наслідків, влучання, загиблі'),
  ('kyiv_alarm',        'Тривога Київ',               'official',
   'тривога по місту з типом загрози (Шахеди / балістика)'),
  ('povitryanatrivoga', 'Повітряна тривога (моніторинг)', 'monitor',
   'зльоти МіГ-31К та пуски — ВИПЕРЕДЖУВАЛЬНА ознака, не лейбл'),
  ('kiev_info0',        'Київ Інфо',                  'monitor',
   'районні попередження і чутки — ознака, не лейбл');

--------------------------------------------------------------------------------
-- Спостереження: одне твердження одного джерела про одну добу
--------------------------------------------------------------------------------

CREATE TABLE attack_observations (
    raid_day        date        NOT NULL,
    region_id       smallint    REFERENCES regions(id),
    source          text        NOT NULL,      -- handle каналу, 'acled', 'kaggle'
    tier            text        NOT NULL CHECK (tier IN ('official','monitor','dataset')),
    metric          text        NOT NULL,
    scope           text        NOT NULL CHECK (scope IN ('kyiv','ua')),
    value           numeric,
    evidence_msg_id bigint,                    -- з якого саме повідомлення взято
    evidence_text   text,
    extracted_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (raid_day, source, metric, scope)
);

COMMENT ON TABLE attack_observations IS
  'Сирі твердження джерел. Рядок ніколи не перезаписується чужим значенням: '
  'розбіжність між джерелами — це дані, а не помилка, і саме на ній будується '
  'впевненість у лейблі.';

COMMENT ON COLUMN attack_observations.metric IS
  'attacked            — чи був удар по Києву (0/1), scope=kyiv
   drone_tracks        — скільки разів зафіксовано БпЛА курсом на Київ, scope=kyiv
   missile_tracks      — те саме для ракет і балістики, scope=kyiv
   drones_launched     — запущено БпЛА за ніч, scope=ua (точне число зі зведення ПС)
   drones_downed       — збито БпЛА, scope=ua
   missiles_launched   — запущено ракет, scope=ua
   missiles_downed     — збито ракет, scope=ua
   impact_locations    — локацій влучань по країні, scope=ua
   impacts             — влучань по місту, scope=kyiv
   killed / injured    — загиблі / поранені по місту, scope=kyiv';

CREATE INDEX attack_obs_day    ON attack_observations (raid_day);
CREATE INDEX attack_obs_metric ON attack_observations (metric, scope);
