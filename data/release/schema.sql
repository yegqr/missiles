--
-- PostgreSQL database dump
--

\restrict c7GbIUk6IC6gQtwUBb7UcvBMfH7TpVt862V02BVV6DA7xSr8lPai90YNi7m3YhL

-- Dumped from database version 16.14
-- Dumped by pg_dump version 16.14

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: kyiv_day(timestamp with time zone); Type: FUNCTION; Schema: public; Owner: missiles
--

CREATE FUNCTION public.kyiv_day(ts timestamp with time zone) RETURNS date
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    AS $$
  SELECT (ts AT TIME ZONE 'Europe/Kyiv')::date;
$$;


ALTER FUNCTION public.kyiv_day(ts timestamp with time zone) OWNER TO missiles;

--
-- Name: kyiv_hour(timestamp with time zone); Type: FUNCTION; Schema: public; Owner: missiles
--

CREATE FUNCTION public.kyiv_hour(ts timestamp with time zone) RETURNS smallint
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    AS $$
  SELECT EXTRACT(hour FROM (ts AT TIME ZONE 'Europe/Kyiv'))::smallint;
$$;


ALTER FUNCTION public.kyiv_hour(ts timestamp with time zone) OWNER TO missiles;

--
-- Name: raid_day(timestamp with time zone); Type: FUNCTION; Schema: public; Owner: missiles
--

CREATE FUNCTION public.raid_day(ts timestamp with time zone) RETURNS date
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    AS $$
  SELECT (((ts AT TIME ZONE 'Europe/Kyiv') - interval '12 hours'))::date;
$$;


ALTER FUNCTION public.raid_day(ts timestamp with time zone) OWNER TO missiles;

--
-- Name: set_updated_at(); Type: FUNCTION; Schema: public; Owner: missiles
--

CREATE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$;


ALTER FUNCTION public.set_updated_at() OWNER TO missiles;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alert_sources; Type: TABLE; Schema: public; Owner: missiles
--

CREATE TABLE public.alert_sources (
    code text NOT NULL,
    priority smallint NOT NULL,
    note text
);


ALTER TABLE public.alert_sources OWNER TO missiles;

--
-- Name: alerts; Type: TABLE; Schema: public; Owner: missiles
--

CREATE TABLE public.alerts (
    id bigint NOT NULL,
    region_id smallint NOT NULL,
    started_at timestamp with time zone NOT NULL,
    finished_at timestamp with time zone,
    alert_type text DEFAULT 'air_raid'::text NOT NULL,
    source text NOT NULL,
    source_alert_id text,
    raw jsonb,
    duration_min numeric GENERATED ALWAYS AS ((EXTRACT(epoch FROM (finished_at - started_at)) / 60.0)) STORED,
    raid_day date GENERATED ALWAYS AS (public.raid_day(started_at)) STORED,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    causes text[],
    CONSTRAINT alerts_source_check CHECK ((source = ANY (ARRAY['official'::text, 'volunteer'::text, 'alerts_in_ua'::text, 'tg_air_alert_ua'::text, 'kyiv_digital'::text]))),
    CONSTRAINT alerts_span_valid CHECK (((finished_at IS NULL) OR (finished_at >= started_at)))
);


ALTER TABLE public.alerts OWNER TO missiles;

--
-- Name: COLUMN alerts.source; Type: COMMENT; Schema: public; Owner: missiles
--

COMMENT ON COLUMN public.alerts.source IS 'official — офіційні канали (з 2022-03-15); volunteer — eTryvoga (з 2022-02-25); alerts_in_ua — лайв API';


--
-- Name: alerts_id_seq; Type: SEQUENCE; Schema: public; Owner: missiles
--

CREATE SEQUENCE public.alerts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.alerts_id_seq OWNER TO missiles;

--
-- Name: alerts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: missiles
--

ALTER SEQUENCE public.alerts_id_seq OWNED BY public.alerts.id;


--
-- Name: attack_events; Type: TABLE; Schema: public; Owner: missiles
--

CREATE TABLE public.attack_events (
    id bigint NOT NULL,
    raid_day date NOT NULL,
    region_id smallint,
    weapon_type text,
    launched integer,
    downed integer,
    impacts integer,
    debris_sites integer,
    source text NOT NULL,
    source_url text,
    raw jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.attack_events OWNER TO missiles;

--
-- Name: attack_events_id_seq; Type: SEQUENCE; Schema: public; Owner: missiles
--

CREATE SEQUENCE public.attack_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.attack_events_id_seq OWNER TO missiles;

--
-- Name: attack_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: missiles
--

ALTER SEQUENCE public.attack_events_id_seq OWNED BY public.attack_events.id;


--
-- Name: attack_observations; Type: TABLE; Schema: public; Owner: missiles
--

CREATE TABLE public.attack_observations (
    raid_day date NOT NULL,
    region_id smallint,
    source text NOT NULL,
    tier text NOT NULL,
    metric text NOT NULL,
    scope text NOT NULL,
    value numeric,
    evidence_msg_id bigint,
    evidence_text text,
    extracted_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT attack_observations_scope_check CHECK ((scope = ANY (ARRAY['kyiv'::text, 'kyiv_obl'::text, 'ua'::text]))),
    CONSTRAINT attack_observations_tier_check CHECK ((tier = ANY (ARRAY['official'::text, 'monitor'::text, 'dataset'::text])))
);


ALTER TABLE public.attack_observations OWNER TO missiles;

--
-- Name: TABLE attack_observations; Type: COMMENT; Schema: public; Owner: missiles
--

COMMENT ON TABLE public.attack_observations IS 'Сирі твердження джерел. Рядок ніколи не перезаписується чужим значенням: розбіжність між джерелами — це дані, а не помилка, і саме на ній будується впевненість у лейблі.';


--
-- Name: COLUMN attack_observations.metric; Type: COMMENT; Schema: public; Owner: missiles
--

COMMENT ON COLUMN public.attack_observations.metric IS 'attacked            — чи був удар по Києву (0/1), scope=kyiv
   drone_tracks        — скільки разів зафіксовано БпЛА курсом на Київ, scope=kyiv
   missile_tracks      — те саме для ракет і балістики, scope=kyiv
   drones_launched     — запущено БпЛА за ніч, scope=ua (точне число зі зведення ПС)
   drones_downed       — збито БпЛА, scope=ua
   missiles_launched   — запущено ракет, scope=ua
   missiles_downed     — збито ракет, scope=ua
   impact_locations    — локацій влучань по країні, scope=ua
   impacts             — влучань по місту, scope=kyiv
   killed / injured    — загиблі / поранені по місту, scope=kyiv';


--
-- Name: COLUMN attack_observations.scope; Type: COMMENT; Schema: public; Owner: missiles
--

COMMENT ON COLUMN public.attack_observations.scope IS 'kyiv — місто; kyiv_obl — Київська область без міста; ua — країна. Три різні величини, які НІКОЛИ не складаються між собою.';


--
-- Name: calendar_days; Type: TABLE; Schema: public; Owner: missiles
--

CREATE TABLE public.calendar_days (
    day date NOT NULL,
    dow smallint NOT NULL,
    month smallint NOT NULL,
    holiday_ua text,
    holiday_ua_w smallint,
    holiday_ru text,
    holiday_ru_w smallint,
    night_hours real,
    heating_season boolean DEFAULT false NOT NULL
);


ALTER TABLE public.calendar_days OWNER TO missiles;

--
-- Name: COLUMN calendar_days.holiday_ua_w; Type: COMMENT; Schema: public; Owner: missiles
--

COMMENT ON COLUMN public.calendar_days.holiday_ua_w IS '3 — Незалежності, Різдво, Великдень, Новий рік; 2 — Конституції, Державності, Захисників, Соборності; 1 — решта пам''ятних дат';


--
-- Name: COLUMN calendar_days.night_hours; Type: COMMENT; Schema: public; Owner: missiles
--

COMMENT ON COLUMN public.calendar_days.night_hours IS 'Темний час доби. Взимку вікно для нічної атаки майже вдвічі довше, ніж улітку.';


--
-- Name: ingest_expectations; Type: TABLE; Schema: public; Owner: missiles
--

CREATE TABLE public.ingest_expectations (
    source text NOT NULL,
    max_age interval NOT NULL,
    description text
);


ALTER TABLE public.ingest_expectations OWNER TO missiles;

--
-- Name: ingest_runs; Type: TABLE; Schema: public; Owner: missiles
--

CREATE TABLE public.ingest_runs (
    id bigint NOT NULL,
    source text NOT NULL,
    mode text NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    status text DEFAULT 'running'::text NOT NULL,
    rows_read integer,
    rows_written integer,
    params jsonb,
    error text,
    CONSTRAINT ingest_runs_mode_check CHECK ((mode = ANY (ARRAY['backfill'::text, 'live'::text]))),
    CONSTRAINT ingest_runs_status_check CHECK ((status = ANY (ARRAY['running'::text, 'ok'::text, 'error'::text, 'skipped'::text])))
);


ALTER TABLE public.ingest_runs OWNER TO missiles;

--
-- Name: ingest_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: missiles
--

CREATE SEQUENCE public.ingest_runs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.ingest_runs_id_seq OWNER TO missiles;

--
-- Name: ingest_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: missiles
--

ALTER SEQUENCE public.ingest_runs_id_seq OWNED BY public.ingest_runs.id;


--
-- Name: losses_daily; Type: TABLE; Schema: public; Owner: missiles
--

CREATE TABLE public.losses_daily (
    raid_day date NOT NULL,
    region_id smallint NOT NULL,
    source text NOT NULL,
    killed integer DEFAULT 0 NOT NULL,
    injured integer DEFAULT 0 NOT NULL,
    source_url text,
    raw jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.losses_daily OWNER TO missiles;

--
-- Name: parse_state; Type: TABLE; Schema: public; Owner: missiles
--

CREATE TABLE public.parse_state (
    parser text NOT NULL,
    channel text,
    last_msg_id bigint,
    last_run_at timestamp with time zone DEFAULT now() NOT NULL,
    rows_written integer
);


ALTER TABLE public.parse_state OWNER TO missiles;

--
-- Name: predictions; Type: TABLE; Schema: public; Owner: missiles
--

CREATE TABLE public.predictions (
    raid_day date NOT NULL,
    target text NOT NULL,
    issued_at timestamp with time zone DEFAULT now() NOT NULL,
    p numeric NOT NULL,
    model text NOT NULL,
    members jsonb,
    prior_shift boolean DEFAULT false NOT NULL,
    n_train integer,
    horizon smallint DEFAULT 1 NOT NULL,
    CONSTRAINT predictions_horizon_check CHECK ((horizon = ANY (ARRAY[1, 2]))),
    CONSTRAINT predictions_p_check CHECK (((p >= (0)::numeric) AND (p <= (1)::numeric))),
    CONSTRAINT predictions_target_check CHECK ((target = ANY (ARRAY['attacked'::text, 'alert30'::text, 'massive'::text])))
);


ALTER TABLE public.predictions OWNER TO missiles;

--
-- Name: TABLE predictions; Type: COMMENT; Schema: public; Owner: missiles
--

COMMENT ON TABLE public.predictions IS 'Один рядок = один виданий прогноз. Рядки НЕ перезаписуються: перепрогноз тієї самої доби додає новий issued_at, і видно, як оцінка змінювалась.';


--
-- Name: COLUMN predictions.members; Type: COMMENT; Schema: public; Owner: missiles
--

COMMENT ON COLUMN public.predictions.members IS 'Склад ансамблю на момент видачі. Склад міняється з кожним дотренуванням, бо моделі відбираються за CV заново — без цього поля прогноз невідтворюваний.';


--
-- Name: COLUMN predictions.horizon; Type: COMMENT; Schema: public; Owner: missiles
--

COMMENT ON COLUMN public.predictions.horizon IS '1 — вікно, що вже почалось (12:00 сьогодні); 2 — наступне вікно (завтра). Обидва прогнози на ту саму raid_day видані в різні дні й різними моделями.';


--
-- Name: readiness_signals; Type: TABLE; Schema: public; Owner: missiles
--

CREATE TABLE public.readiness_signals (
    id bigint NOT NULL,
    ts timestamp with time zone NOT NULL,
    signal_type text NOT NULL,
    platform text,
    airfield text,
    is_standdown boolean DEFAULT false NOT NULL,
    source text NOT NULL,
    msg_id bigint,
    evidence text,
    raid_day date GENERATED ALWAYS AS (public.raid_day(ts)) STORED
);


ALTER TABLE public.readiness_signals OWNER TO missiles;

--
-- Name: COLUMN readiness_signals.is_standdown; Type: COMMENT; Schema: public; Owner: missiles
--

COMMENT ON COLUMN public.readiness_signals.is_standdown IS 'true = «відбій загрози по МіГ-31К». Пара зліт+відбій дає тривалість загрози, а це змістовніша величина, ніж сам факт зльоту.';


--
-- Name: readiness_signals_id_seq; Type: SEQUENCE; Schema: public; Owner: missiles
--

CREATE SEQUENCE public.readiness_signals_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.readiness_signals_id_seq OWNER TO missiles;

--
-- Name: readiness_signals_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: missiles
--

ALTER SEQUENCE public.readiness_signals_id_seq OWNED BY public.readiness_signals.id;


--
-- Name: regions; Type: TABLE; Schema: public; Owner: missiles
--

CREATE TABLE public.regions (
    id smallint NOT NULL,
    code text NOT NULL,
    name_uk text NOT NULL,
    name_en text,
    level text NOT NULL,
    parent_id smallint,
    alerts_in_ua_uid integer,
    lat double precision,
    lon double precision,
    is_tracked boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT regions_level_check CHECK ((level = ANY (ARRAY['oblast'::text, 'raion'::text, 'hromada'::text])))
);


ALTER TABLE public.regions OWNER TO missiles;

--
-- Name: TABLE regions; Type: COMMENT; Schema: public; Owner: missiles
--

COMMENT ON TABLE public.regions IS 'Території моніторингу. Київ-місто і Київська область — окремі рядки.';


--
-- Name: regions_id_seq; Type: SEQUENCE; Schema: public; Owner: missiles
--

CREATE SEQUENCE public.regions_id_seq
    AS smallint
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.regions_id_seq OWNER TO missiles;

--
-- Name: regions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: missiles
--

ALTER SEQUENCE public.regions_id_seq OWNED BY public.regions.id;


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: missiles
--

CREATE TABLE public.schema_migrations (
    filename text NOT NULL,
    applied_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.schema_migrations OWNER TO missiles;

--
-- Name: tg_channels; Type: TABLE; Schema: public; Owner: missiles
--

CREATE TABLE public.tg_channels (
    handle text NOT NULL,
    title text NOT NULL,
    tier text NOT NULL,
    role text NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    added_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT tg_channels_tier_check CHECK ((tier = ANY (ARRAY['official'::text, 'monitor'::text, 'dataset'::text])))
);


ALTER TABLE public.tg_channels OWNER TO missiles;

--
-- Name: COLUMN tg_channels.tier; Type: COMMENT; Schema: public; Owner: missiles
--

COMMENT ON COLUMN public.tg_channels.tier IS 'official — держоргани й ПС, лише вони формують лейбли; monitor — моніторингові канали, тільки ознаки, НІКОЛИ не лейбли; dataset — зовнішній набір для звірки';


--
-- Name: tg_messages; Type: TABLE; Schema: public; Owner: missiles
--

CREATE TABLE public.tg_messages (
    channel text NOT NULL,
    msg_id bigint NOT NULL,
    posted_at timestamp with time zone NOT NULL,
    text text NOT NULL,
    fetched_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.tg_messages OWNER TO missiles;

--
-- Name: tg_scan_state; Type: TABLE; Schema: public; Owner: missiles
--

CREATE TABLE public.tg_scan_state (
    channel text NOT NULL,
    min_msg_id bigint,
    max_msg_id bigint,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.tg_scan_state OWNER TO missiles;

--
-- Name: threat_events; Type: TABLE; Schema: public; Owner: missiles
--

CREATE TABLE public.threat_events (
    id bigint NOT NULL,
    region_id smallint NOT NULL,
    ts timestamp with time zone NOT NULL,
    threat_type text NOT NULL,
    msg_id bigint
);


ALTER TABLE public.threat_events OWNER TO missiles;

--
-- Name: threat_events_id_seq; Type: SEQUENCE; Schema: public; Owner: missiles
--

CREATE SEQUENCE public.threat_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.threat_events_id_seq OWNER TO missiles;

--
-- Name: threat_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: missiles
--

ALTER SEQUENCE public.threat_events_id_seq OWNED BY public.threat_events.id;


--
-- Name: v_alert_hours; Type: VIEW; Schema: public; Owner: missiles
--

CREATE VIEW public.v_alert_hours AS
 SELECT a.id AS alert_id,
    a.region_id,
    a.source,
    h.hour_ts,
    public.kyiv_hour(h.hour_ts) AS kyiv_hour,
    public.raid_day(h.hour_ts) AS raid_day,
    (EXTRACT(epoch FROM (LEAST(COALESCE(a.finished_at, now()), (h.hour_ts + '01:00:00'::interval)) - GREATEST(a.started_at, h.hour_ts))) / 60.0) AS minutes
   FROM (public.alerts a
     CROSS JOIN LATERAL generate_series(date_trunc('hour'::text, a.started_at), date_trunc('hour'::text, COALESCE(a.finished_at, now())), '01:00:00'::interval) h(hour_ts));


ALTER VIEW public.v_alert_hours OWNER TO missiles;

--
-- Name: VIEW v_alert_hours; Type: COMMENT; Schema: public; Owner: missiles
--

COMMENT ON VIEW public.v_alert_hours IS 'Тривоги, розкладені по годинних кошиках, з кількістю хвилин у кожному';


--
-- Name: v_alert_parts; Type: VIEW; Schema: public; Owner: missiles
--

CREATE VIEW public.v_alert_parts AS
 WITH contrib AS (
         SELECT a.region_id AS canon_region_id,
            a.region_id AS src_region_id,
            a.started_at,
            LEAST(COALESCE(a.finished_at, now()), (a.started_at + '24:00:00'::interval)) AS finished_at,
            (a.finished_at IS NULL) AS is_open,
            a.source,
            'own'::text AS part
           FROM public.alerts a
        UNION ALL
         SELECT r.parent_id,
            a.region_id,
            a.started_at,
            LEAST(COALESCE(a.finished_at, now()), (a.started_at + '24:00:00'::interval)) AS "least",
            (a.finished_at IS NULL),
            a.source,
            'raion'::text
           FROM (public.alerts a
             JOIN public.regions r ON ((r.id = a.region_id)))
          WHERE ((r.level = 'raion'::text) AND (r.parent_id IS NOT NULL))
        ), pri AS (
         SELECT c.canon_region_id,
            c.src_region_id,
            c.started_at,
            c.finished_at,
            c.is_open,
            c.source,
            c.part,
            s.priority
           FROM (contrib c
             JOIN public.alert_sources s ON ((s.code = c.source)))
        )
 SELECT canon_region_id,
    src_region_id,
    started_at,
    finished_at,
    source,
    part
   FROM pri p
  WHERE (NOT (EXISTS ( SELECT 1
           FROM pri h
          WHERE ((h.canon_region_id = p.canon_region_id) AND (h.priority < p.priority) AND (h.started_at < p.finished_at) AND (p.started_at < h.finished_at)))));


ALTER VIEW public.v_alert_parts OWNER TO missiles;

--
-- Name: VIEW v_alert_parts; Type: COMMENT; Schema: public; Owner: missiles
--

COMMENT ON VIEW public.v_alert_parts IS 'Внески в канонічний ряд. Джерело нижчого пріоритету відкидається лише там, де реально перекривається з вищим. Відкритий інтервал закінчується min(зараз, старт + 24 год): майбутні хвилини не нараховуються, а загублений відбій не дає тривоги, довшої за добу.';


--
-- Name: v_alerts_canonical; Type: VIEW; Schema: public; Owner: missiles
--

CREATE VIEW public.v_alerts_canonical AS
 WITH p AS (
         SELECT v_alert_parts.canon_region_id,
            v_alert_parts.started_at,
            COALESCE(v_alert_parts.finished_at, now()) AS finished_at,
            (v_alert_parts.finished_at IS NULL) AS is_open,
            v_alert_parts.source,
            v_alert_parts.part
           FROM public.v_alert_parts
        ), marked AS (
         SELECT p.canon_region_id,
            p.started_at,
            p.finished_at,
            p.is_open,
            p.source,
            p.part,
            max(p.finished_at) OVER (PARTITION BY p.canon_region_id ORDER BY p.started_at ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prev_end
           FROM p
        ), grouped AS (
         SELECT marked.canon_region_id,
            marked.started_at,
            marked.finished_at,
            marked.is_open,
            marked.source,
            marked.part,
            marked.prev_end,
            sum(
                CASE
                    WHEN ((marked.prev_end IS NULL) OR (marked.started_at > marked.prev_end)) THEN 1
                    ELSE 0
                END) OVER (PARTITION BY marked.canon_region_id ORDER BY marked.started_at) AS island
           FROM marked
        )
 SELECT r.code AS region_code,
    g.canon_region_id AS region_id,
    min(g.started_at) AS started_at,
        CASE
            WHEN bool_or(g.is_open) THEN NULL::timestamp with time zone
            ELSE max(g.finished_at)
        END AS finished_at,
    round((EXTRACT(epoch FROM (max(g.finished_at) - min(g.started_at))) / 60.0)) AS duration_min,
    public.raid_day(min(g.started_at)) AS raid_day,
    string_agg(DISTINCT g.part, '+'::text ORDER BY g.part) AS parts,
    count(*) AS merged_from
   FROM (grouped g
     JOIN public.regions r ON ((r.id = g.canon_region_id)))
  GROUP BY r.code, g.canon_region_id, g.island;


ALTER VIEW public.v_alerts_canonical OWNER TO missiles;

--
-- Name: VIEW v_alerts_canonical; Type: COMMENT; Schema: public; Owner: missiles
--

COMMENT ON VIEW public.v_alerts_canonical IS 'Один безрозривний ряд тривог на регіон. Колонка parts показує походження інтервалу.';


--
-- Name: v_alerts_daily; Type: VIEW; Schema: public; Owner: missiles
--

CREATE VIEW public.v_alerts_daily AS
 WITH hrs AS (
         SELECT v_alert_hours.region_id,
            v_alert_hours.source,
            v_alert_hours.raid_day,
            v_alert_hours.kyiv_hour,
            v_alert_hours.alert_id,
            v_alert_hours.minutes
           FROM public.v_alert_hours
        )
 SELECT r.code AS region_code,
    h.region_id,
    h.source,
    h.raid_day,
    count(DISTINCT h.alert_id) AS alerts_count,
    round(sum(h.minutes)) AS total_minutes,
    round(sum(h.minutes) FILTER (WHERE ((h.kyiv_hour >= 22) OR (h.kyiv_hour < 6)))) AS night_minutes,
    round(max(per_alert.minutes)) AS longest_alert_minutes
   FROM ((hrs h
     JOIN public.regions r ON ((r.id = h.region_id)))
     JOIN LATERAL ( SELECT sum(h2.minutes) AS minutes
           FROM hrs h2
          WHERE (h2.alert_id = h.alert_id)) per_alert ON (true))
  GROUP BY r.code, h.region_id, h.source, h.raid_day;


ALTER VIEW public.v_alerts_daily OWNER TO missiles;

--
-- Name: v_canon_hours; Type: VIEW; Schema: public; Owner: missiles
--

CREATE VIEW public.v_canon_hours AS
 SELECT c.region_id,
    c.region_code,
    h.hour_ts,
    public.kyiv_hour(h.hour_ts) AS kyiv_hour,
    public.raid_day(h.hour_ts) AS raid_day,
    (EXTRACT(epoch FROM (LEAST(COALESCE(c.finished_at, now()), (h.hour_ts + '01:00:00'::interval)) - GREATEST(c.started_at, h.hour_ts))) / 60.0) AS minutes,
    c.started_at AS alert_started_at
   FROM (public.v_alerts_canonical c
     CROSS JOIN LATERAL generate_series(date_trunc('hour'::text, c.started_at), date_trunc('hour'::text, COALESCE(c.finished_at, now())), '01:00:00'::interval) h(hour_ts));


ALTER VIEW public.v_canon_hours OWNER TO missiles;

--
-- Name: v_canon_daily; Type: VIEW; Schema: public; Owner: missiles
--

CREATE VIEW public.v_canon_daily AS
 SELECT region_code,
    region_id,
    raid_day,
    count(DISTINCT alert_started_at) FILTER (WHERE (public.raid_day(alert_started_at) = raid_day)) AS alerts_count,
    round(sum(minutes)) AS total_minutes,
    COALESCE(round(sum(minutes) FILTER (WHERE ((kyiv_hour >= 22) OR (kyiv_hour < 6)))), (0)::numeric) AS night_minutes
   FROM public.v_canon_hours
  GROUP BY region_code, region_id, raid_day;


ALTER VIEW public.v_canon_daily OWNER TO missiles;

--
-- Name: VIEW v_canon_daily; Type: COMMENT; Schema: public; Owner: missiles
--

COMMENT ON VIEW public.v_canon_daily IS 'Добові агрегати тривог. total_minutes/night_minutes діляться між добами нальоту пропорційно годинам; alerts_count рахує подію один раз — у добі, коли тривога почалась.';


--
-- Name: weather_forecast; Type: TABLE; Schema: public; Owner: missiles
--

CREATE TABLE public.weather_forecast (
    location_id smallint NOT NULL,
    issued_at timestamp with time zone NOT NULL,
    ts timestamp with time zone NOT NULL,
    temperature_2m real,
    precipitation real,
    cloud_cover smallint,
    cloud_cover_low smallint,
    visibility real,
    wind_speed_10m real,
    wind_speed_100m real,
    wind_gusts_10m real,
    wind_direction_10m smallint,
    surface_pressure real,
    weather_code smallint
);


ALTER TABLE public.weather_forecast OWNER TO missiles;

--
-- Name: weather_hourly; Type: TABLE; Schema: public; Owner: missiles
--

CREATE TABLE public.weather_hourly (
    location_id smallint NOT NULL,
    ts timestamp with time zone NOT NULL,
    source text NOT NULL,
    temperature_2m real,
    apparent_temperature real,
    relative_humidity_2m smallint,
    dew_point_2m real,
    precipitation real,
    rain real,
    snowfall real,
    cloud_cover smallint,
    cloud_cover_low smallint,
    cloud_cover_mid smallint,
    cloud_cover_high smallint,
    visibility real,
    wind_speed_10m real,
    wind_speed_100m real,
    wind_gusts_10m real,
    wind_direction_10m smallint,
    surface_pressure real,
    pressure_msl real,
    weather_code smallint,
    is_day boolean,
    fetched_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT weather_hourly_source_check CHECK ((source = ANY (ARRAY['era5_archive'::text, 'forecast'::text])))
);


ALTER TABLE public.weather_hourly OWNER TO missiles;

--
-- Name: COLUMN weather_hourly.source; Type: COMMENT; Schema: public; Owner: missiles
--

COMMENT ON COLUMN public.weather_hourly.source IS 'era5_archive — реаналіз ERA5 (лаг ~5 діб, еталон); forecast — оперативна модель, перезаписується архівом';


--
-- Name: COLUMN weather_hourly.visibility; Type: COMMENT; Schema: public; Owner: missiles
--

COMMENT ON COLUMN public.weather_hourly.visibility IS 'NULL в ERA5-архіві: змінна доступна лише у forecast-API';


--
-- Name: weather_locations; Type: TABLE; Schema: public; Owner: missiles
--

CREATE TABLE public.weather_locations (
    id smallint NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    lat double precision NOT NULL,
    lon double precision NOT NULL
);


ALTER TABLE public.weather_locations OWNER TO missiles;

--
-- Name: v_coverage; Type: VIEW; Schema: public; Owner: missiles
--

CREATE VIEW public.v_coverage AS
 SELECT ((('alerts:'::text || a.source) || ':'::text) || r.code) AS stream,
    min(a.started_at) AS from_ts,
    max(a.started_at) AS to_ts,
    count(*) AS rows
   FROM (public.alerts a
     JOIN public.regions r ON ((r.id = a.region_id)))
  GROUP BY ((('alerts:'::text || a.source) || ':'::text) || r.code)
UNION ALL
 SELECT ((('weather:'::text || w.source) || ':'::text) || l.code) AS stream,
    min(w.ts) AS from_ts,
    max(w.ts) AS to_ts,
    count(*) AS rows
   FROM (public.weather_hourly w
     JOIN public.weather_locations l ON ((l.id = w.location_id)))
  GROUP BY ((('weather:'::text || w.source) || ':'::text) || l.code)
UNION ALL
 SELECT ('forecast:'::text || l.code) AS stream,
    min(f.ts) AS from_ts,
    max(f.ts) AS to_ts,
    count(*) AS rows
   FROM (public.weather_forecast f
     JOIN public.weather_locations l ON ((l.id = f.location_id)))
  GROUP BY ('forecast:'::text || l.code);


ALTER VIEW public.v_coverage OWNER TO missiles;

--
-- Name: v_label_attacked; Type: VIEW; Schema: public; Owner: missiles
--

CREATE VIEW public.v_label_attacked AS
 WITH votes AS (
         SELECT attack_observations.raid_day,
            attack_observations.source,
            max(attack_observations.value) AS v
           FROM public.attack_observations
          WHERE ((attack_observations.metric = 'attacked'::text) AND (attack_observations.scope = 'kyiv'::text) AND (attack_observations.tier = 'official'::text))
          GROUP BY attack_observations.raid_day, attack_observations.source
        )
 SELECT raid_day,
    count(*) AS "джерел",
    count(*) FILTER (WHERE (v = (1)::numeric)) AS "за",
    count(*) FILTER (WHERE (v = (0)::numeric)) AS "проти",
    (count(*) FILTER (WHERE (v = (1)::numeric)) > count(*) FILTER (WHERE (v = (0)::numeric))) AS attacked,
        CASE
            WHEN (count(*) FILTER (WHERE (v = (1)::numeric)) = count(*)) THEN 'повна згода'::text
            WHEN (count(*) FILTER (WHERE (v = (0)::numeric)) = count(*)) THEN 'повна згода'::text
            ELSE 'РОЗБІЖНІСТЬ'::text
        END AS "впевненість"
   FROM votes
  GROUP BY raid_day;


ALTER VIEW public.v_label_attacked OWNER TO missiles;

--
-- Name: v_label_counts; Type: VIEW; Schema: public; Owner: missiles
--

CREATE VIEW public.v_label_counts AS
 SELECT raid_day,
    metric,
    scope,
    count(*) AS "джерел",
    percentile_cont((0.5)::double precision) WITHIN GROUP (ORDER BY ((value)::double precision)) AS "значення",
    min(value) AS "мін",
    max(value) AS "макс",
    ((max(value) - min(value)) > (0.1 * NULLIF(max(value), (0)::numeric))) AS "суперечність"
   FROM public.attack_observations
  WHERE ((tier = ANY (ARRAY['official'::text, 'dataset'::text])) AND (value IS NOT NULL))
  GROUP BY raid_day, metric, scope;


ALTER VIEW public.v_label_counts OWNER TO missiles;

--
-- Name: v_daily_labels; Type: VIEW; Schema: public; Owner: missiles
--

CREATE VIEW public.v_daily_labels AS
 WITH days AS (
         SELECT attack_observations.raid_day
           FROM public.attack_observations
        UNION
         SELECT v_canon_daily.raid_day
           FROM public.v_canon_daily
          WHERE (v_canon_daily.region_code = 'kyiv_city'::text)
        ), wide AS (
         SELECT v_label_counts.raid_day,
            max(v_label_counts."значення") FILTER (WHERE ((v_label_counts.metric = 'drone_tracks'::text) AND (v_label_counts.scope = 'kyiv'::text))) AS drone_tracks_kyiv,
            max(v_label_counts."значення") FILTER (WHERE ((v_label_counts.metric = 'missile_tracks'::text) AND (v_label_counts.scope = 'kyiv'::text))) AS missile_tracks_kyiv,
            max(v_label_counts."значення") FILTER (WHERE ((v_label_counts.metric = 'drone_tracks'::text) AND (v_label_counts.scope = 'kyiv_obl'::text))) AS drone_tracks_obl,
            max(v_label_counts."значення") FILTER (WHERE ((v_label_counts.metric = 'missile_tracks'::text) AND (v_label_counts.scope = 'kyiv_obl'::text))) AS missile_tracks_obl,
            max(v_label_counts."значення") FILTER (WHERE ((v_label_counts.metric = 'impacts'::text) AND (v_label_counts.scope = 'kyiv'::text))) AS impacts_kyiv,
            max(v_label_counts."значення") FILTER (WHERE ((v_label_counts.metric = 'killed'::text) AND (v_label_counts.scope = 'kyiv'::text))) AS killed_kyiv,
            max(v_label_counts."значення") FILTER (WHERE ((v_label_counts.metric = 'injured'::text) AND (v_label_counts.scope = 'kyiv'::text))) AS injured_kyiv,
            max(v_label_counts."значення") FILTER (WHERE ((v_label_counts.metric = 'drones_launched'::text) AND (v_label_counts.scope = 'ua'::text))) AS drones_launched_ua,
            max(v_label_counts."значення") FILTER (WHERE ((v_label_counts.metric = 'targets_downed'::text) AND (v_label_counts.scope = 'ua'::text))) AS targets_downed_ua,
            max(v_label_counts."значення") FILTER (WHERE ((v_label_counts.metric = 'missiles_launched'::text) AND (v_label_counts.scope = 'ua'::text))) AS missiles_launched_ua,
            max(v_label_counts."значення") FILTER (WHERE ((v_label_counts.metric = 'impact_locations'::text) AND (v_label_counts.scope = 'ua'::text))) AS impact_locations_ua,
            bool_or(v_label_counts."суперечність") AS "є_суперечність"
           FROM public.v_label_counts
          GROUP BY v_label_counts.raid_day
        )
 SELECT d.raid_day,
    COALESCE(a.attacked, (w.drone_tracks_kyiv > (0)::double precision)) AS attacked_kyiv,
    COALESCE(a."впевненість", 'немає джерел'::text) AS attacked_confidence,
    w.drone_tracks_kyiv,
    w.missile_tracks_kyiv,
    w.drone_tracks_obl,
    w.missile_tracks_obl,
    w.impacts_kyiv,
    w.killed_kyiv,
    w.injured_kyiv,
    w.drones_launched_ua,
    w.targets_downed_ua,
    w.missiles_launched_ua,
    w.impact_locations_ua,
    COALESCE(w."є_суперечність", false) AS "є_суперечність",
    COALESCE(al.alerts_count, (0)::bigint) AS alerts_count,
    COALESCE(al.total_minutes, (0)::numeric) AS alert_minutes,
    COALESCE(al.night_minutes, (0)::numeric) AS alert_night_minutes
   FROM (((days d
     LEFT JOIN public.v_label_attacked a ON ((a.raid_day = d.raid_day)))
     LEFT JOIN wide w ON ((w.raid_day = d.raid_day)))
     LEFT JOIN public.v_canon_daily al ON (((al.raid_day = d.raid_day) AND (al.region_code = 'kyiv_city'::text))));


ALTER VIEW public.v_daily_labels OWNER TO missiles;

--
-- Name: VIEW v_daily_labels; Type: COMMENT; Schema: public; Owner: missiles
--

COMMENT ON VIEW public.v_daily_labels IS 'attacked_kyiv = NULL означає «жодне джерело нічого не стверджувало». Треки міста й області — різні колонки: лейбл будується ТІЛЬКИ з міських.';


--
-- Name: v_readiness_daily; Type: VIEW; Schema: public; Owner: missiles
--

CREATE VIEW public.v_readiness_daily AS
 WITH mig_up AS (
         SELECT r.ts,
            r.raid_day,
            ( SELECT min(s.ts) AS min
                   FROM public.readiness_signals s
                  WHERE ((s.platform = 'mig31k'::text) AND s.is_standdown AND (s.ts > r.ts) AND (s.ts < (r.ts + '12:00:00'::interval)))) AS down_ts
           FROM public.readiness_signals r
          WHERE ((r.platform = 'mig31k'::text) AND (NOT r.is_standdown))
        ), mig AS (
         SELECT mig_up.raid_day,
            count(*) AS takeoffs,
            avg((EXTRACT(epoch FROM (mig_up.down_ts - mig_up.ts)) / 60.0)) AS threat_minutes,
            count(*) FILTER (WHERE (mig_up.down_ts IS NULL)) AS unresolved
           FROM mig_up
          GROUP BY mig_up.raid_day
        ), other AS (
         SELECT readiness_signals.raid_day,
            count(*) FILTER (WHERE (readiness_signals.platform = ANY (ARRAY['tu95'::text, 'tu160'::text]))) AS strategic_takeoffs,
            count(*) FILTER (WHERE (readiness_signals.platform = 'kalibr_ship'::text)) AS kalibr_signals
           FROM public.readiness_signals
          GROUP BY readiness_signals.raid_day
        )
 SELECT COALESCE(m.raid_day, o.raid_day) AS raid_day,
    COALESCE(m.takeoffs, (0)::bigint) AS mig31k_takeoffs,
    COALESCE(o.strategic_takeoffs, (0)::bigint) AS strategic_takeoffs,
    COALESCE(o.kalibr_signals, (0)::bigint) AS kalibr_signals,
    m.threat_minutes AS mig31k_threat_minutes,
    COALESCE(m.unresolved, (0)::bigint) AS mig31k_unresolved
   FROM (mig m
     FULL JOIN other o ON ((o.raid_day = m.raid_day)));


ALTER VIEW public.v_readiness_daily OWNER TO missiles;

--
-- Name: COLUMN v_readiness_daily.mig31k_threat_minutes; Type: COMMENT; Schema: public; Owner: missiles
--

COMMENT ON COLUMN public.v_readiness_daily.mig31k_threat_minutes IS 'Середня тривалість пари «зліт -> найближчий відбій» у межах 12 годин. NULL означає, що жоден зліт доби не отримав відбою — це не нуль.';


--
-- Name: COLUMN v_readiness_daily.mig31k_unresolved; Type: COMMENT; Schema: public; Owner: missiles
--

COMMENT ON COLUMN public.v_readiness_daily.mig31k_unresolved IS 'Скільки зльотів доби лишились без відбою. Росте, коли канал змінює формулювання — дешевий детектор тихої деградації парсера.';


--
-- Name: v_weather_daily; Type: VIEW; Schema: public; Owner: missiles
--

CREATE VIEW public.v_weather_daily AS
 SELECT l.code AS location_code,
    w.location_id,
    public.raid_day(w.ts) AS raid_day,
    count(*) AS hours_observed,
    avg(w.temperature_2m) AS temp_avg,
    min(w.temperature_2m) AS temp_min,
    max(w.temperature_2m) AS temp_max,
    sum(w.precipitation) AS precip_sum,
    avg(w.cloud_cover) AS cloud_avg,
    avg(w.cloud_cover_low) AS cloud_low_avg,
    avg(w.wind_speed_10m) AS wind_avg,
    max(w.wind_gusts_10m) AS gust_max,
    avg(w.wind_direction_10m) AS wind_dir_avg,
    avg(w.surface_pressure) AS pressure_avg,
    avg(w.relative_humidity_2m) AS humidity_avg,
    avg(w.cloud_cover) FILTER (WHERE ((public.kyiv_hour(w.ts) >= 22) OR (public.kyiv_hour(w.ts) < 6))) AS night_cloud_avg,
    avg(w.cloud_cover_low) FILTER (WHERE ((public.kyiv_hour(w.ts) >= 22) OR (public.kyiv_hour(w.ts) < 6))) AS night_cloud_low_avg,
    avg(w.wind_speed_10m) FILTER (WHERE ((public.kyiv_hour(w.ts) >= 22) OR (public.kyiv_hour(w.ts) < 6))) AS night_wind_avg,
    sum(w.precipitation) FILTER (WHERE ((public.kyiv_hour(w.ts) >= 22) OR (public.kyiv_hour(w.ts) < 6))) AS night_precip_sum,
    avg(w.temperature_2m) FILTER (WHERE ((public.kyiv_hour(w.ts) >= 22) OR (public.kyiv_hour(w.ts) < 6))) AS night_temp_avg
   FROM (public.weather_hourly w
     JOIN public.weather_locations l ON ((l.id = w.location_id)))
  GROUP BY l.code, w.location_id, (public.raid_day(w.ts));


ALTER VIEW public.v_weather_daily OWNER TO missiles;

--
-- Name: v_daily_features; Type: VIEW; Schema: public; Owner: missiles
--

CREATE VIEW public.v_daily_features AS
 SELECT c.day AS raid_day,
    c.dow,
    c.month,
    c.night_hours,
    c.heating_season,
    c.holiday_ua,
    COALESCE((c.holiday_ua_w)::integer, 0) AS holiday_ua_w,
    c.holiday_ru,
    COALESCE((c.holiday_ru_w)::integer, 0) AS holiday_ru_w,
    COALESCE(pl.alerts_count, (0)::bigint) AS alerts_prev,
    COALESCE(pl.alert_minutes, (0)::numeric) AS alert_minutes_prev,
    COALESCE(pl.drone_tracks_kyiv, (0)::double precision) AS drone_tracks_prev,
    COALESCE(pl.missile_tracks_kyiv, (0)::double precision) AS missile_tracks_prev,
    COALESCE(pl.drone_tracks_obl, (0)::double precision) AS drone_tracks_obl_prev,
    COALESCE(pl.missile_tracks_obl, (0)::double precision) AS missile_tracks_obl_prev,
    COALESCE(pl.drones_launched_ua, (0)::double precision) AS drones_launched_ua_prev,
    COALESCE(pr.mig31k_takeoffs, (0)::bigint) AS mig31k_prev,
    COALESCE(pr.strategic_takeoffs, (0)::bigint) AS strategic_prev,
    COALESCE(pr.kalibr_signals, (0)::bigint) AS kalibr_prev,
    fw.night_cloud_low_avg,
    fw.night_wind_avg,
    fw.night_temp_avg,
    fw.night_precip_sum,
    l.attacked_kyiv AS y_attacked,
    COALESCE(l.drone_tracks_kyiv, (0)::double precision) AS y_drone_tracks,
    COALESCE(l.missile_tracks_kyiv, (0)::double precision) AS y_missile_tracks,
    COALESCE(l.drone_tracks_obl, (0)::double precision) AS y_drone_tracks_obl,
    COALESCE(l.alert_minutes, (0)::numeric) AS y_alert_minutes,
    COALESCE(rd.mig31k_takeoffs, (0)::bigint) AS mig31k_same_window
   FROM (((((public.calendar_days c
     LEFT JOIN public.v_daily_labels l ON ((l.raid_day = c.day)))
     LEFT JOIN public.v_daily_labels pl ON ((pl.raid_day = (c.day - 1))))
     LEFT JOIN public.v_readiness_daily pr ON ((pr.raid_day = (c.day - 1))))
     LEFT JOIN public.v_readiness_daily rd ON ((rd.raid_day = c.day)))
     LEFT JOIN public.v_weather_daily fw ON (((fw.raid_day = c.day) AND (fw.location_code = 'kyiv'::text))))
  WHERE (c.day >= '2022-02-24'::date);


ALTER VIEW public.v_daily_features OWNER TO missiles;

--
-- Name: v_freshness; Type: VIEW; Schema: public; Owner: missiles
--

CREATE VIEW public.v_freshness AS
 SELECT r.code AS region_code,
    max(a.started_at) AS "остання_тривога",
    (now() - max(a.updated_at)) AS "давність_запису"
   FROM (public.alerts a
     JOIN public.regions r ON ((r.id = a.region_id)))
  GROUP BY r.code;


ALTER VIEW public.v_freshness OWNER TO missiles;

--
-- Name: v_health; Type: VIEW; Schema: public; Owner: missiles
--

CREATE VIEW public.v_health AS
 SELECT e.source,
    e.description,
    last.finished_at AS "остання_вдала",
    (now() - last.finished_at) AS "давність",
    e.max_age AS "дозволено",
        CASE
            WHEN (last.finished_at IS NULL) THEN 'ніколи не запускався'::text
            WHEN ((now() - last.finished_at) > e.max_age) THEN 'ПРОТУХ'::text
            WHEN (last.status = 'skipped'::text) THEN ('пропущено: '::text || COALESCE(last.note, ''::text))
            ELSE 'ok'::text
        END AS "стан",
    fail.n AS "невдач_за_добу"
   FROM ((public.ingest_expectations e
     LEFT JOIN LATERAL ( SELECT r.finished_at,
            r.status,
            (r.params ->> 'reason'::text) AS note
           FROM public.ingest_runs r
          WHERE ((r.source = e.source) AND (r.status = ANY (ARRAY['ok'::text, 'skipped'::text])))
          ORDER BY r.finished_at DESC
         LIMIT 1) last ON (true))
     LEFT JOIN LATERAL ( SELECT count(*) AS n
           FROM public.ingest_runs r
          WHERE ((r.source = e.source) AND (r.status = 'error'::text) AND (r.started_at > (now() - '24:00:00'::interval)))) fail ON (true));


ALTER VIEW public.v_health OWNER TO missiles;

--
-- Name: VIEW v_health; Type: COMMENT; Schema: public; Owner: missiles
--

COMMENT ON VIEW public.v_health IS 'Стан кожного потоку інжесту. Рядок «ПРОТУХ» = джерело мовчить довше дозволеного.';


--
-- Name: v_hourly_features; Type: VIEW; Schema: public; Owner: missiles
--

CREATE VIEW public.v_hourly_features AS
 SELECT w.ts,
    public.raid_day(w.ts) AS raid_day,
    public.kyiv_hour(w.ts) AS kyiv_hour,
    w.temperature_2m,
    w.precipitation,
    w.cloud_cover,
    w.cloud_cover_low,
    w.visibility,
    w.wind_speed_10m,
    w.wind_speed_100m,
    w.wind_direction_10m,
    w.surface_pressure,
    w.relative_humidity_2m,
    COALESCE(city.minutes, (0)::numeric) AS kyiv_city_alert_minutes,
    COALESCE(obl.minutes, (0)::numeric) AS kyiv_oblast_alert_minutes,
    (COALESCE(city.minutes, (0)::numeric) > (0)::numeric) AS kyiv_city_alert
   FROM (((public.weather_hourly w
     JOIN public.weather_locations l ON (((l.id = w.location_id) AND (l.code = 'kyiv'::text))))
     LEFT JOIN LATERAL ( SELECT sum(ch.minutes) AS minutes
           FROM public.v_canon_hours ch
          WHERE ((ch.hour_ts = w.ts) AND (ch.region_code = 'kyiv_city'::text))) city ON (true))
     LEFT JOIN LATERAL ( SELECT sum(ch.minutes) AS minutes
           FROM public.v_canon_hours ch
          WHERE ((ch.hour_ts = w.ts) AND (ch.region_code = 'kyiv_oblast'::text))) obl ON (true));


ALTER VIEW public.v_hourly_features OWNER TO missiles;

--
-- Name: v_prediction_scores; Type: VIEW; Schema: public; Owner: missiles
--

CREATE VIEW public.v_prediction_scores AS
 WITH last_pred AS (
         SELECT DISTINCT ON (predictions.raid_day, predictions.target, predictions.horizon) predictions.raid_day,
            predictions.target,
            predictions.horizon,
            predictions.p,
            predictions.issued_at,
            predictions.model
           FROM public.predictions
          ORDER BY predictions.raid_day, predictions.target, predictions.horizon, predictions.issued_at DESC
        ), fact AS (
         SELECT v_daily_features.raid_day,
            v_daily_features.y_attacked AS attacked,
            (v_daily_features.y_alert_minutes >= (30)::numeric) AS alert30,
            (((v_daily_features.y_drone_tracks + v_daily_features.y_missile_tracks) > (0)::double precision) AND ((v_daily_features.y_alert_minutes >= (480)::numeric) OR (v_daily_features.y_drone_tracks >= (15)::double precision))) AS massive
           FROM public.v_daily_features
        )
 SELECT lp.raid_day,
    lp.target,
    lp.horizon,
    lp.p,
    lp.issued_at,
    lp.model,
    (lp.model !~~ 'backtest%'::text) AS live,
        CASE lp.target
            WHEN 'attacked'::text THEN f.attacked
            WHEN 'alert30'::text THEN f.alert30
            WHEN 'massive'::text THEN f.massive
            ELSE NULL::boolean
        END AS "факт",
    ((lp.p - (
        CASE lp.target
            WHEN 'attacked'::text THEN (f.attacked)::integer
            WHEN 'alert30'::text THEN (f.alert30)::integer
            WHEN 'massive'::text THEN (f.massive)::integer
            ELSE NULL::integer
        END)::numeric) ^ (2)::numeric) AS brier
   FROM (last_pred lp
     JOIN fact f ON ((f.raid_day = lp.raid_day)))
  WHERE (lp.raid_day < (((now() AT TIME ZONE 'Europe/Kyiv'::text) - '12:00:00'::interval))::date);


ALTER VIEW public.v_prediction_scores OWNER TO missiles;

--
-- Name: weather_locations_id_seq; Type: SEQUENCE; Schema: public; Owner: missiles
--

CREATE SEQUENCE public.weather_locations_id_seq
    AS smallint
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.weather_locations_id_seq OWNER TO missiles;

--
-- Name: weather_locations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: missiles
--

ALTER SEQUENCE public.weather_locations_id_seq OWNED BY public.weather_locations.id;


--
-- Name: alerts id; Type: DEFAULT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.alerts ALTER COLUMN id SET DEFAULT nextval('public.alerts_id_seq'::regclass);


--
-- Name: attack_events id; Type: DEFAULT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.attack_events ALTER COLUMN id SET DEFAULT nextval('public.attack_events_id_seq'::regclass);


--
-- Name: ingest_runs id; Type: DEFAULT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.ingest_runs ALTER COLUMN id SET DEFAULT nextval('public.ingest_runs_id_seq'::regclass);


--
-- Name: readiness_signals id; Type: DEFAULT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.readiness_signals ALTER COLUMN id SET DEFAULT nextval('public.readiness_signals_id_seq'::regclass);


--
-- Name: regions id; Type: DEFAULT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.regions ALTER COLUMN id SET DEFAULT nextval('public.regions_id_seq'::regclass);


--
-- Name: threat_events id; Type: DEFAULT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.threat_events ALTER COLUMN id SET DEFAULT nextval('public.threat_events_id_seq'::regclass);


--
-- Name: weather_locations id; Type: DEFAULT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.weather_locations ALTER COLUMN id SET DEFAULT nextval('public.weather_locations_id_seq'::regclass);


--
-- Name: alert_sources alert_sources_pkey; Type: CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.alert_sources
    ADD CONSTRAINT alert_sources_pkey PRIMARY KEY (code);


--
-- Name: alerts alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_pkey PRIMARY KEY (id);


--
-- Name: attack_events attack_events_pkey; Type: CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.attack_events
    ADD CONSTRAINT attack_events_pkey PRIMARY KEY (id);


--
-- Name: attack_events attack_events_raid_day_region_id_weapon_type_source_key; Type: CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.attack_events
    ADD CONSTRAINT attack_events_raid_day_region_id_weapon_type_source_key UNIQUE (raid_day, region_id, weapon_type, source);


--
-- Name: attack_observations attack_observations_pkey; Type: CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.attack_observations
    ADD CONSTRAINT attack_observations_pkey PRIMARY KEY (raid_day, source, metric, scope);


--
-- Name: calendar_days calendar_days_pkey; Type: CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.calendar_days
    ADD CONSTRAINT calendar_days_pkey PRIMARY KEY (day);


--
-- Name: ingest_expectations ingest_expectations_pkey; Type: CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.ingest_expectations
    ADD CONSTRAINT ingest_expectations_pkey PRIMARY KEY (source);


--
-- Name: ingest_runs ingest_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.ingest_runs
    ADD CONSTRAINT ingest_runs_pkey PRIMARY KEY (id);


--
-- Name: losses_daily losses_daily_pkey; Type: CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.losses_daily
    ADD CONSTRAINT losses_daily_pkey PRIMARY KEY (raid_day, region_id, source);


--
-- Name: parse_state parse_state_pkey; Type: CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.parse_state
    ADD CONSTRAINT parse_state_pkey PRIMARY KEY (parser);


--
-- Name: predictions predictions_pkey; Type: CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.predictions
    ADD CONSTRAINT predictions_pkey PRIMARY KEY (raid_day, target, horizon, issued_at);


--
-- Name: readiness_signals readiness_signals_pkey; Type: CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.readiness_signals
    ADD CONSTRAINT readiness_signals_pkey PRIMARY KEY (id);


--
-- Name: readiness_signals readiness_signals_source_msg_id_signal_type_key; Type: CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.readiness_signals
    ADD CONSTRAINT readiness_signals_source_msg_id_signal_type_key UNIQUE (source, msg_id, signal_type);


--
-- Name: regions regions_code_key; Type: CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.regions
    ADD CONSTRAINT regions_code_key UNIQUE (code);


--
-- Name: regions regions_pkey; Type: CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.regions
    ADD CONSTRAINT regions_pkey PRIMARY KEY (id);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (filename);


--
-- Name: tg_channels tg_channels_pkey; Type: CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.tg_channels
    ADD CONSTRAINT tg_channels_pkey PRIMARY KEY (handle);


--
-- Name: tg_messages tg_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.tg_messages
    ADD CONSTRAINT tg_messages_pkey PRIMARY KEY (channel, msg_id);


--
-- Name: tg_scan_state tg_scan_state_pkey; Type: CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.tg_scan_state
    ADD CONSTRAINT tg_scan_state_pkey PRIMARY KEY (channel);


--
-- Name: threat_events threat_events_pkey; Type: CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.threat_events
    ADD CONSTRAINT threat_events_pkey PRIMARY KEY (id);


--
-- Name: threat_events threat_events_region_id_ts_threat_type_key; Type: CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.threat_events
    ADD CONSTRAINT threat_events_region_id_ts_threat_type_key UNIQUE (region_id, ts, threat_type);


--
-- Name: weather_forecast weather_forecast_pkey; Type: CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.weather_forecast
    ADD CONSTRAINT weather_forecast_pkey PRIMARY KEY (location_id, issued_at, ts);


--
-- Name: weather_hourly weather_hourly_pkey; Type: CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.weather_hourly
    ADD CONSTRAINT weather_hourly_pkey PRIMARY KEY (location_id, ts);


--
-- Name: weather_locations weather_locations_code_key; Type: CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.weather_locations
    ADD CONSTRAINT weather_locations_code_key UNIQUE (code);


--
-- Name: weather_locations weather_locations_pkey; Type: CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.weather_locations
    ADD CONSTRAINT weather_locations_pkey PRIMARY KEY (id);


--
-- Name: alerts_one_open; Type: INDEX; Schema: public; Owner: missiles
--

CREATE UNIQUE INDEX alerts_one_open ON public.alerts USING btree (source, region_id, alert_type) WHERE (finished_at IS NULL);


--
-- Name: alerts_open; Type: INDEX; Schema: public; Owner: missiles
--

CREATE INDEX alerts_open ON public.alerts USING btree (region_id) WHERE (finished_at IS NULL);


--
-- Name: alerts_raid_day; Type: INDEX; Schema: public; Owner: missiles
--

CREATE INDEX alerts_raid_day ON public.alerts USING btree (raid_day);


--
-- Name: alerts_region_time; Type: INDEX; Schema: public; Owner: missiles
--

CREATE INDEX alerts_region_time ON public.alerts USING btree (region_id, started_at DESC);


--
-- Name: alerts_uniq; Type: INDEX; Schema: public; Owner: missiles
--

CREATE UNIQUE INDEX alerts_uniq ON public.alerts USING btree (source, region_id, alert_type, started_at);


--
-- Name: attack_obs_day; Type: INDEX; Schema: public; Owner: missiles
--

CREATE INDEX attack_obs_day ON public.attack_observations USING btree (raid_day);


--
-- Name: attack_obs_metric; Type: INDEX; Schema: public; Owner: missiles
--

CREATE INDEX attack_obs_metric ON public.attack_observations USING btree (metric, scope);


--
-- Name: ingest_runs_source_time; Type: INDEX; Schema: public; Owner: missiles
--

CREATE INDEX ingest_runs_source_time ON public.ingest_runs USING btree (source, started_at DESC);


--
-- Name: predictions_day; Type: INDEX; Schema: public; Owner: missiles
--

CREATE INDEX predictions_day ON public.predictions USING btree (raid_day, target);


--
-- Name: readiness_day; Type: INDEX; Schema: public; Owner: missiles
--

CREATE INDEX readiness_day ON public.readiness_signals USING btree (raid_day);


--
-- Name: readiness_time; Type: INDEX; Schema: public; Owner: missiles
--

CREATE INDEX readiness_time ON public.readiness_signals USING btree (ts);


--
-- Name: tg_messages_time; Type: INDEX; Schema: public; Owner: missiles
--

CREATE INDEX tg_messages_time ON public.tg_messages USING btree (channel, posted_at);


--
-- Name: threat_events_time; Type: INDEX; Schema: public; Owner: missiles
--

CREATE INDEX threat_events_time ON public.threat_events USING btree (ts);


--
-- Name: weather_forecast_ts; Type: INDEX; Schema: public; Owner: missiles
--

CREATE INDEX weather_forecast_ts ON public.weather_forecast USING btree (ts);


--
-- Name: weather_hourly_ts; Type: INDEX; Schema: public; Owner: missiles
--

CREATE INDEX weather_hourly_ts ON public.weather_hourly USING btree (ts);


--
-- Name: alerts alerts_updated_at; Type: TRIGGER; Schema: public; Owner: missiles
--

CREATE TRIGGER alerts_updated_at BEFORE UPDATE ON public.alerts FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: alerts alerts_region_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_region_id_fkey FOREIGN KEY (region_id) REFERENCES public.regions(id);


--
-- Name: attack_events attack_events_region_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.attack_events
    ADD CONSTRAINT attack_events_region_id_fkey FOREIGN KEY (region_id) REFERENCES public.regions(id);


--
-- Name: attack_observations attack_observations_region_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.attack_observations
    ADD CONSTRAINT attack_observations_region_id_fkey FOREIGN KEY (region_id) REFERENCES public.regions(id);


--
-- Name: losses_daily losses_daily_region_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.losses_daily
    ADD CONSTRAINT losses_daily_region_id_fkey FOREIGN KEY (region_id) REFERENCES public.regions(id);


--
-- Name: regions regions_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.regions
    ADD CONSTRAINT regions_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.regions(id);


--
-- Name: threat_events threat_events_region_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.threat_events
    ADD CONSTRAINT threat_events_region_id_fkey FOREIGN KEY (region_id) REFERENCES public.regions(id);


--
-- Name: weather_forecast weather_forecast_location_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.weather_forecast
    ADD CONSTRAINT weather_forecast_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.weather_locations(id);


--
-- Name: weather_hourly weather_hourly_location_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: missiles
--

ALTER TABLE ONLY public.weather_hourly
    ADD CONSTRAINT weather_hourly_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.weather_locations(id);


--
-- PostgreSQL database dump complete
--

\unrestrict c7GbIUk6IC6gQtwUBb7UcvBMfH7TpVt862V02BVV6DA7xSr8lPai90YNi7m3YhL

