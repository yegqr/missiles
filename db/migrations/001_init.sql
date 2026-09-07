-- 001_init: базові таблиці (довідники, тривоги, погода, лог інжесту)
-- Уся часова вісь зберігається в UTC (timestamptz). Локальний день — Europe/Kyiv.

--------------------------------------------------------------------------------
-- Хелпери часу
--------------------------------------------------------------------------------

-- "Ніч обстрілу" не збігається з календарною добою: наліт 07.09 23:00 -> 08.09 05:00
-- це одна подія. raid_day зсуває добу на 12 годин: доба триває з 12:00 до 12:00
-- за київським часом і підписується датою її початку.
CREATE OR REPLACE FUNCTION raid_day(ts timestamptz)
RETURNS date
LANGUAGE sql
IMMUTABLE            -- формально STABLE (залежить від tzdata), позначено IMMUTABLE
PARALLEL SAFE        -- свідомо, щоб використовувати в generated-колонках та індексах
AS $$
  SELECT (((ts AT TIME ZONE 'Europe/Kyiv') - interval '12 hours'))::date;
$$;

CREATE OR REPLACE FUNCTION kyiv_day(ts timestamptz)
RETURNS date LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT (ts AT TIME ZONE 'Europe/Kyiv')::date;
$$;

CREATE OR REPLACE FUNCTION kyiv_hour(ts timestamptz)
RETURNS smallint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT EXTRACT(hour FROM (ts AT TIME ZONE 'Europe/Kyiv'))::smallint;
$$;

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$;

--------------------------------------------------------------------------------
-- Довідник територій
--------------------------------------------------------------------------------

CREATE TABLE regions (
    id              smallserial PRIMARY KEY,
    code            text        NOT NULL UNIQUE,   -- kyiv_city, kyiv_oblast, kyiv_obl_brovary...
    name_uk         text        NOT NULL,
    name_en         text,
    level           text        NOT NULL CHECK (level IN ('oblast','raion','hromada')),
    parent_id       smallint    REFERENCES regions(id),
    alerts_in_ua_uid integer,                      -- uid у API alerts.in.ua
    lat             double precision,
    lon             double precision,
    is_tracked      boolean     NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE regions IS 'Території моніторингу. Київ-місто і Київська область — окремі рядки.';

--------------------------------------------------------------------------------
-- Тривоги
--------------------------------------------------------------------------------

CREATE TABLE alerts (
    id              bigserial   PRIMARY KEY,
    region_id       smallint    NOT NULL REFERENCES regions(id),
    started_at      timestamptz NOT NULL,
    finished_at     timestamptz,                   -- NULL = тривога триває
    alert_type      text        NOT NULL DEFAULT 'air_raid',
    source          text        NOT NULL CHECK (source IN ('official','volunteer','alerts_in_ua')),
    source_alert_id text,
    raw             jsonb,
    duration_min    numeric GENERATED ALWAYS AS
                        (EXTRACT(epoch FROM (finished_at - started_at))/60.0) STORED,
    raid_day        date    GENERATED ALWAYS AS (raid_day(started_at)) STORED,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT alerts_span_valid CHECK (finished_at IS NULL OR finished_at >= started_at)
);

-- Одна й та сама тривога з одного джерела не дублюється
CREATE UNIQUE INDEX alerts_uniq ON alerts (source, region_id, alert_type, started_at);
-- В межах джерела може бути тільки одна відкрита тривога на регіон
CREATE UNIQUE INDEX alerts_one_open ON alerts (source, region_id, alert_type)
    WHERE finished_at IS NULL;
CREATE INDEX alerts_region_time  ON alerts (region_id, started_at DESC);
CREATE INDEX alerts_raid_day     ON alerts (raid_day);
CREATE INDEX alerts_open         ON alerts (region_id) WHERE finished_at IS NULL;

CREATE TRIGGER alerts_updated_at BEFORE UPDATE ON alerts
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON COLUMN alerts.source IS
  'official — офіційні канали (з 2022-03-15); volunteer — eTryvoga (з 2022-02-25); alerts_in_ua — лайв API';

--------------------------------------------------------------------------------
-- Погода
--------------------------------------------------------------------------------

CREATE TABLE weather_locations (
    id      smallserial PRIMARY KEY,
    code    text NOT NULL UNIQUE,
    name    text NOT NULL,
    lat     double precision NOT NULL,
    lon     double precision NOT NULL
);

-- Фактична (спостережена) погода по годинах
CREATE TABLE weather_hourly (
    location_id           smallint    NOT NULL REFERENCES weather_locations(id),
    ts                    timestamptz NOT NULL,
    source                text        NOT NULL CHECK (source IN ('era5_archive','forecast')),
    temperature_2m        real,
    apparent_temperature  real,
    relative_humidity_2m  smallint,
    dew_point_2m          real,
    precipitation         real,
    rain                  real,
    snowfall              real,
    cloud_cover           smallint,
    cloud_cover_low       smallint,
    cloud_cover_mid       smallint,
    cloud_cover_high      smallint,
    visibility            real,
    wind_speed_10m        real,
    wind_speed_100m       real,
    wind_gusts_10m        real,
    wind_direction_10m    smallint,
    surface_pressure      real,
    pressure_msl          real,
    weather_code          smallint,
    is_day                boolean,
    fetched_at            timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (location_id, ts)
);
CREATE INDEX weather_hourly_ts ON weather_hourly (ts);
COMMENT ON COLUMN weather_hourly.source IS
  'era5_archive — реаналіз ERA5 (лаг ~5 діб, еталон); forecast — оперативна модель, перезаписується архівом';
COMMENT ON COLUMN weather_hourly.visibility IS
  'NULL в ERA5-архіві: змінна доступна лише у forecast-API';

-- Прогноз на майбутнє: зберігаємо зріз (issued_at) окремо від факту
CREATE TABLE weather_forecast (
    location_id           smallint    NOT NULL REFERENCES weather_locations(id),
    issued_at             timestamptz NOT NULL,
    ts                    timestamptz NOT NULL,
    temperature_2m        real,
    precipitation         real,
    cloud_cover           smallint,
    cloud_cover_low       smallint,
    visibility            real,
    wind_speed_10m        real,
    wind_speed_100m       real,
    wind_gusts_10m        real,
    wind_direction_10m    smallint,
    surface_pressure      real,
    weather_code          smallint,
    PRIMARY KEY (location_id, issued_at, ts)
);
CREATE INDEX weather_forecast_ts ON weather_forecast (ts);

--------------------------------------------------------------------------------
-- Фаза 2: засоби ураження та втрати (для індексів I(t) та C(t))
--------------------------------------------------------------------------------

CREATE TABLE attack_events (
    id           bigserial PRIMARY KEY,
    raid_day     date        NOT NULL,
    region_id    smallint    REFERENCES regions(id),
    weapon_type  text,                    -- shahed, kh101, iskander_m, kab...
    launched     integer,
    downed       integer,
    impacts      integer,
    debris_sites integer,
    source       text        NOT NULL,    -- ps_zsu, kmva, dsns, telegram
    source_url   text,
    raw          jsonb,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (raid_day, region_id, weapon_type, source)
);

CREATE TABLE losses_daily (
    raid_day    date        NOT NULL,
    region_id   smallint    NOT NULL REFERENCES regions(id),
    source      text        NOT NULL,
    killed      integer     NOT NULL DEFAULT 0,
    injured     integer     NOT NULL DEFAULT 0,
    source_url  text,
    raw         jsonb,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (raid_day, region_id, source)
);

--------------------------------------------------------------------------------
-- Лог інжесту
--------------------------------------------------------------------------------

CREATE TABLE ingest_runs (
    id            bigserial PRIMARY KEY,
    source        text        NOT NULL,
    mode          text        NOT NULL CHECK (mode IN ('backfill','live')),
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    status        text        NOT NULL DEFAULT 'running'
                              CHECK (status IN ('running','ok','error')),
    rows_read     integer,
    rows_written  integer,
    params        jsonb,
    error         text
);
CREATE INDEX ingest_runs_source_time ON ingest_runs (source, started_at DESC);

--------------------------------------------------------------------------------
-- Довідникові дані
--------------------------------------------------------------------------------

INSERT INTO regions (code, name_uk, name_en, level, alerts_in_ua_uid, lat, lon) VALUES
  ('kyiv_city',   'м. Київ',            'Kyiv',          'oblast', 31, 50.4501, 30.5234),
  ('kyiv_oblast', 'Київська область',   'Kyiv Oblast',   'oblast', 14, 50.0500, 30.5000);

INSERT INTO regions (code, name_uk, name_en, level, parent_id, lat, lon)
SELECT v.code, v.name_uk, v.name_en, 'raion', r.id, v.lat, v.lon
FROM regions r,
     (VALUES
        ('kyiv_obl_vyshhorod',   'Вишгородський район',   'Vyshhorod Raion',   50.585, 30.487),
        ('kyiv_obl_brovary',     'Броварський район',     'Brovary Raion',     50.511, 30.790),
        ('kyiv_obl_boryspil',    'Бориспільський район',  'Boryspil Raion',    50.353, 30.955),
        ('kyiv_obl_obukhiv',     'Обухівський район',     'Obukhiv Raion',     50.107, 30.622),
        ('kyiv_obl_bucha',       'Бучанський район',      'Bucha Raion',       50.545, 30.212),
        ('kyiv_obl_fastiv',      'Фастівський район',     'Fastiv Raion',      50.075, 29.918),
        ('kyiv_obl_bila_tserkva','Білоцерківський район', 'Bila Tserkva Raion',49.796, 30.115)
     ) AS v(code, name_uk, name_en, lat, lon)
WHERE r.code = 'kyiv_oblast';

INSERT INTO weather_locations (code, name, lat, lon) VALUES
  ('kyiv', 'Київ (центр)', 50.4501, 30.5234);
