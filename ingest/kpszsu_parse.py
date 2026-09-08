#!/usr/bin/env python3
"""Канал Повітряних Сил -> спостереження для лейблів.

З одного каналу беремо дві РІЗНІ речі, і плутати їх не можна:

1. Добове зведення (щоранку) — точні числа за ніч, але ПО КРАЇНІ:
   скільки запущено БпЛА і ракет, скільки збито. scope='ua'.

2. Повідомлення супроводу цілей у реальному часі — єдине, що взагалі
   існує з київською прив'язкою: «Реактивні БпЛА курсом на Київ»,
   «Балістика на Київ!». Це НЕ кількість бортів (одне повідомлення може
   означати групу), тому метрика чесно зветься *_tracks. scope='kyiv'.

Формат зведень мінявся за чотири роки: числа то цифрами, то словами
(«ЗБИТО П'ЯТЬ УДАРНИХ ДРОНІВ»), структура різна. Тому парсимо консервативно:
що впевнено не розпізналось — не вигадуємо, а лишаємо порожнім і рахуємо
в статистиці покриття. Кожне число зберігає уривок тексту, з якого взяте.
"""
import re
import sys
from datetime import datetime, timedelta, date
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
import db

CHANNEL = "kpszsu"
KYIV = ZoneInfo("Europe/Kyiv")
NL = "§¶"

WORDS = {
    "один": 1, "одну": 1, "одного": 1, "два": 2, "дві": 2, "двома": 2,
    "три": 3, "трьома": 3, "чотири": 4, "п'ять": 5, "пʼять": 5, "п’ять": 5,
    "шість": 6, "сім": 7, "вісім": 8, "дев'ять": 9, "девʼять": 9, "дев’ять": 9,
    "десять": 10, "одинадцять": 11, "дванадцять": 12, "тринадцять": 13,
    "чотирнадцять": 14, "п'ятнадцять": 15, "пʼятнадцять": 15,
    "шістнадцять": 16, "сімнадцять": 17, "вісімнадцять": 18,
    "дев'ятнадцять": 19, "двадцять": 20,
}

# КИЇВСЬКА ПРИВ'ЯЗКА — газетир, зібраний із самих текстів каналу
#
# Задача: відрізнити ціль над МІСТОМ від цілі над областю. Канал майже ніколи
# не пише «Київ» у службовому вигляді — він пише як пишуть люди:
#     «Балістика на Київ!»            «🚀Швидкісна ціль Київ!»
#     «Реактивний БпЛА над Києвом»    «"Шахед" ➡️ в межах столиці!»
#     «Київ - реактивні БпЛА над містом (Позняки, ДВРЗ)»
# і водночас рясно називає НП області: Бровари 433 рази, Бориспіль 213,
# Васильків 200, Славутич 189, Вишгород 157.
#
# Три словники замість однієї регулярки:
#   OBLAST_TOK — регіональні токени («Київщина», «Київська», «Київське
#                водосховище», «Київський напрямок»). Вирізаються з тексту
#                ПЕРЕД пошуком міста: інакше підрядок «на Київ» знаходиться
#                всередині «на Київщині» і область стає містом.
#   CITY       — форми назви міста плюс «столиця».
#   DISTRICT   — місцевості САМОГО міста. Потрібні, бо канал інколи називає
#                лише їх: «Реактивний БпЛА - Лукʼянівка/Шулявка!». Мають
#                пріоритет над обласним токеном: «Київщина - БпЛА повз ДВРЗ»
#                це насправді місто.
#
# Ознаки руху («курс», «напрямок») тут НЕ вимагаються. Спроба вимагати їх
# коштувала 571 втраченого повідомлення, серед них балістика й «Кинджали»
# на Київ: канал часто пише саму подію без дієслова.
RE_OBLAST_TOK = re.compile(
    r"Київщин\w*|Київськ\w*|Київське\s+водосховищ\w*|Київського\s+водосховищ\w*", re.I)

RE_CITY = re.compile(
    r"\bКиїв\b|\bКиєв[аоуі]\b|\bКиєвом\b|\bКиїву\b|\bКиїва\b|"
    r"м\.?\s*Київ|на\s+Київ\b|у\s+Київ\b|в\s+Київ\b|над\s+Києвом|"
    r"столиц\w*", re.I)

# Лише однозначні назви. «Борщагівка» пропущена навмисно: є і район міста,
# і Софіївська/Петропавлівська Борщагівка в області. «Поділ» пропущений, бо
# збігається з Подільськом на Одещині та зі звичайним словом.
RE_CITY_DISTRICT = re.compile(
    r"Позняк\w*|Троєщин\w*|Оболон[ьі]|Дарниц\w*|Печерськ\w*|Голосіїв\w*|"
    r"Святошин\w*|Виноградар\w*|Осокорк\w*|Русанівк\w*|Теремк\w*|Куренівк\w*|"
    r"Лук['’ʼ]янівк\w*|Шулявк\w*|Чоколівк\w*|Солом['’ʼ]янк\w*|ДВРЗ|Бортнич\w*|"
    r"Вигурівщин\w*|Академмістечк\w*|Відрадн\w+\s+проспект", re.I)

# НП Київської області. Використовуються не для заборони (повідомлення
# «повз Бориспіль - курсом на м.Київ» — це місто), а щоб рахувати ОКРЕМУ
# величину: цілі над областю. 1439 таких повідомлень раніше просто зникали.
RE_OBLAST_NP = re.compile(
    r"\bБровар\w*|\bБориспол\w*|\bБориспіл\w*|\bВишгород\w*|\bОбухів\w*|"
    r"\bОбухова\b|\bФастів\w*|\bБуч[аиі]\b|\bБучанськ\w*|\bБіла\s+Церкв\w*|"
    r"\bБілої\s+Церкв\w*|\bБілоцерк\w*|\bІрпін\w*|\bІрпен\w*|\bВасильків\b|"
    r"\bВасилькова\b|\bВасильківськ\w*|\bСлавутич\w*|\bПереяслав\w*|"
    r"\bІванків\w*|\bІванкова\b|\bГостомел\w*|\bДимер\w*|\bЯготин\w*|"
    r"\bКагарлик\w*|\bВишнев[еого]\w*|\bБородянк\w*|\bМакарів\w*|\bРжищів\w*|"
    r"\bБаришівк\w*|\bБерезан[ьі]\b|\bБогуслав\w*|\bМиронівк\w*|\bСквир\w*|"
    r"\bТетіїв\w*|\bУзин\b|\bУкраїнк[аиі]\b|\bБоярк\w*|\bКозин\b|\bГлевах\w*|"
    r"\bКалинівк\w*|\bБаришівськ\w*|\bПогреб\w*|\bЗазим['’ʼ]\w*", re.I)

# Не повідомлення про ціль: позивний підрозділу, відбій загрози, репости новин.
RE_NOT_TARGET = re.compile(
    r"Привид\w*\s+Києв|відбій|Підписуйся|Подписаться|Obozrevatel|#stoprussia", re.I)


def city_target(text: str) -> bool:
    """Чи йдеться про ціль над МІСТОМ Київ."""
    if RE_NOT_TARGET.search(text):
        return False
    if RE_CITY_DISTRICT.search(text):      # район міста названо прямо
        return True
    return bool(RE_CITY.search(RE_OBLAST_TOK.sub(" ", text)))


def oblast_target(text: str) -> bool:
    """Ціль над Київською ОБЛАСТЮ, але не над містом.

    Окрема величина, а не лейбл: удар по області не є ударом по місту, але
    ціль за 30 км від нього — змістовна випереджувальна ознака.
    """
    if RE_NOT_TARGET.search(text) or city_target(text):
        return False
    return bool(RE_OBLAST_NP.search(text) or RE_OBLAST_TOK.search(text))


RE_DRONE  = re.compile(r"бпла|шахед|shahed|герань|гербера|дрон|пародія|"
                       r"бандероль|s8000", re.I)
RE_BALL   = re.compile(r"балістик|іскандер|kn-23|с-400|кинджал|кинжал", re.I)
RE_MISSILE= re.compile(r"ракет|калібр|х-101|х-555|х-59|х-22|х-31|крилат", re.I)

# Зведення впізнаємо за заголовком, а не за наявністю чисел. Форми заголовка
# канал міняє: «ЗНИЩЕНО 13 УДАРНИХ БПЛА», «ЗНЕШКОДЖЕНО 56 ВОРОЖИХ БПЛА»,
# «РАКЕТНА АТАКА ТЕРОРИСТІВ» — стара форма губила 177 зведень, серед них
# 08.07.2024 (удар по Охматдиту).
RE_SUMMARY = re.compile(r"ЗБИТО|ПОДАВЛЕНО|ЗНИЩЕНО|ЗНЕШКОДЖЕНО|У ніч на|"
                        r"Протягом ночі|РАКЕТНА АТАКА|Генеральний штаб", re.I)

# Заголовок зведення — це рядки про ЗБИТІ цілі. Числа «запущено» стоять нижче,
# у тілі. Якщо шукати по всьому тексту, перший збіг завжди належить заголовку,
# і «ЗБИТО 51 ІЗ 70 РАКЕТ» читається як «запущено 51». Тому тіло й заголовок
# розділяються, і кожна метрика шукається лише у своїй частині.
RE_HEAD_LINE = re.compile(r"ЗБИТО|ПОДАВЛЕНО|ЗНИЩЕНО|ЗНЕШКОДЖЕНО|вдалось збити", re.I)


def split_summary(text: str):
    """(заголовок про збиті, тіло про запущені)."""
    head, body = [], []
    for line in text.split("\n"):
        (head if RE_HEAD_LINE.search(line) else body).append(line)
    return "\n".join(head), "\n".join(body)


def raid_day(ts):
    return ((ts.astimezone(KYIV)) - timedelta(hours=12)).date()


def summary_day(ts):
    """Доба нальоту, яку ОПИСУЄ зведення.

    Зведення завжди підбиває ніч, що вже минула («У ніч на 7 вересня…»), тобто
    добу нальоту, яка закінчилась опівдні. Ранкове зведення raid_day() відносить
    правильно, а вечірнє (84 з 821) — на добу вперед, у майбутнє, і затирає там
    чуже. Правило одне для обох: київська дата публікації мінус доба."""
    return (ts.astimezone(KYIV)).date() - timedelta(days=1)


def num(token):
    token = token.strip().lower()
    if token.isdigit():
        return int(token)
    return WORDS.get(token)


def _find(patterns, text):
    """Перше число, що знайшлося хоч одним із шаблонів."""
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            for g in m.groups():
                v = num(g) if g else None
                if v is not None:
                    return v, text[max(0, m.start() - 40):m.end() + 40]
    return None, None


# «атакував 164-ма ударними БпЛА», «атакував 92 ударними БпЛА типу Shahed»
LAUNCHED_DRONES = [
    r"атак\w*\s+(?:Україну\s+)?(\d+)[-\s]*(?:ма|ьма)?\s*ударн\w*\s+БпЛА",
    r"атак\w*\s+(?:Україну\s+)?([а-яїієґ']+)[-\s]*(?:ма|ьма)?\s*ударн\w*\s+БпЛА",
    r"зафіксовано пуски\s+(\d+)",
    r"(\d+)[-\s]*(?:ма|ьма)?\s*ударн\w+\s+БпЛА",
]
# Скільки збито. Заголовок може перелічувати кілька типів: «ЗБИТО/ПОДАВЛЕНО
# 41 РАКЕТУ ТА 652 ВОРОЖІ БПЛА» — беремо СУМУ, а не перше число, інакше
# «збито» дорівнює лише кількості ракет (41 замість 693).
DOWNED_TOTAL = [
    r"(?:ЗБИТО/ПОДАВЛЕНО|ЗБИТО|ПОДАВЛЕНО|ЗНИЩЕНО|ЗНЕШКОДЖЕНО|вдалось збити)\s+(\d+)",
    r"(?:ЗБИТО|ЗНИЩЕНО)\s+([А-ЯЇІЄҐа-яїієґ']+)\s",
]
RE_DOWNED_EXTRA = re.compile(r"\bта\s+(\d+)\s+(?:ворож\w+\s+)?(?:БПЛА|БпЛА|дрон)", re.I)
# «атакував 11-ма балістичними ракетами», «56 крилатих ракет»
LAUNCHED_MISSILES = [
    r"атак\w*\s+(\d+)[-\s]*(?:ма|ьма)?\s*(?:балістичн\w+|крилат\w+|аеробалістичн\w+)?\s*ракет",
    r"(\d+)[-\s]*(?:ма|ьма)?\s*крилат\w+\s+ракет",
    r"(\d+)[-\s]*(?:ма|ьма)?\s*балістичн\w+\s+ракет",
    r"(\d+)\s+РАКЕТ",
    r"([а-яїієґ']+)\s+керован\w+\s+авіаційн\w+\s+ракет",
]
IMPACT_LOC = [r"влучання[^.]{0,60}?на\s+(\d+)\s+локаці"]


def parse_summary(text):
    """-> dict метрика -> (значення, уривок). Порожній, якщо це не зведення."""
    head, body = split_summary(text)
    out = {}
    # «Запущено» шукаємо ТІЛЬКИ в тілі: у заголовку стоять збиті.
    for key, pats in (("drones_launched", LAUNCHED_DRONES),
                      ("missiles_launched", LAUNCHED_MISSILES)):
        v, ev = _find(pats, body)
        if v is not None:
            out[key] = (v, ev)
    v, ev = _find(IMPACT_LOC, text)
    if v is not None:
        out["impact_locations"] = (v, ev)

    v, ev = _find(DOWNED_TOTAL, head or text)
    if v is not None:
        extra = RE_DOWNED_EXTRA.search(head or text)
        if extra:
            v += int(extra.group(1))
        out["targets_downed"] = (v, ev)

    # Запобіжник від найгіршої помилки цього парсера: «запущено» ніколи не може
    # бути меншим за «збито». Якщо вийшло так — число взято не звідти, і краще
    # не мати значення, ніж мати неправильне.
    td = out.get("targets_downed", (None,))[0]
    if td is not None:
        for k in ("drones_launched", "missiles_launched"):
            if k in out and out[k][0] < td and out[k][0] < 0.5 * td:
                del out[k]
    return out


def track_kind(text):
    if RE_BALL.search(text):
        return "missile_tracks"
    if RE_MISSILE.search(text):
        return "missile_tracks"
    if RE_DRONE.search(text):
        return "drone_tracks"
    return None


def run():
    rows = db.query(f"""
        SELECT msg_id, posted_at, replace(text, chr(10), '{NL}')
        FROM tg_messages WHERE channel = '{CHANNEL}' ORDER BY msg_id""")

    summaries = {}          # raid_day -> {metric: (value, evidence)}
    tracks = {}             # (raid_day, metric) -> [count, приклад]
    n_sum = n_sum_parsed = n_track = 0

    for msg_id, ts_raw, raw in rows:
        text = raw.replace(NL, "\n")
        ts = datetime.fromisoformat(ts_raw.replace(" ", "T"))
        day = raid_day(ts)

        if RE_SUMMARY.search(text.split("\n")[0]) and len(text) > 300:
            n_sum += 1
            got = parse_summary(text)
            if got:
                n_sum_parsed += 1
                summaries.setdefault(summary_day(
                    datetime.fromisoformat(ts_raw.replace(" ", "T"))), {}).update(got)
            continue

        # Супровід цілей. Місто й область — дві РІЗНІ величини: удар по області
        # не є ударом по місту, але ціль за 30 км від нього — змістовна ознака.
        if len(text) < 400:
            kind = track_kind(text)
            if kind and city_target(text):
                n_track += 1
                k = (day, kind, "kyiv")
                if k not in tracks:
                    tracks[k] = [0, msg_id, text[:200]]
                tracks[k][0] += 1
            elif kind and oblast_target(text):
                k = (day, kind, "kyiv_obl")
                if k not in tracks:
                    tracks[k] = [0, msg_id, text[:200]]
                tracks[k][0] += 1

    # ЯВНІ НУЛІ. Без них у лейблі будуть самі одиниці, і модель навчиться
    # відповідати «так» завжди. Але нуль — це твердження «атаки не було», і
    # ставити його можна лише там, де джерело справді могло її побачити.
    #
    # Стара умова «≥5 повідомлень за добу» міряла активність КАНАЛУ, а не теми:
    # у 2022 канал писав про наземні бої, умова виконувалась, і доба 27.02.2022
    # з 21 годиною тривоги в Києві отримувала «атаки не було». Це рівно той
    # «найгірший тип брудних даних» із METHODOLOGY §7 — непомітний, бо розмітка
    # виглядає повною.
    #
    # Нова умова, три запобіжники разом:
    #   1) канал того дня писав про ПОВІТРЯНУ обстановку (а не про що завгодно);
    #   2) у місті не було тривалої тривоги — інакше твердження суперечить
    #      незалежному тракту (реєстру КМДА), і ми просто мовчимо;
    #   3) доба належить періоду, коли супровід цілей узагалі публікувався.
    RE_AIR = re.compile(r"БпЛА|шахед|ракет|балістик|тривог|повітрян|збито|"
                        r"подавлен|МіГ|Ту-95|Ту-160|укритт", re.I)
    alive, air = {}, {}
    for msg_id, ts_raw, raw in rows:
        d = raid_day(datetime.fromisoformat(ts_raw.replace(" ", "T")))
        alive[d] = alive.get(d, 0) + 1
        if RE_AIR.search(raw.replace(NL, "\n")):
            air[d] = air.get(d, 0) + 1
    ALIVE_MIN = 5      # менше повідомлень за добу — вважаємо, що каналу не було
    AIR_MIN = 3        # і серед них щонайменше три про повітряну обстановку
    ZERO_FROM = date(2023, 7, 1)   # раніше формат супроводу ще не склався

    # Тривалі тривоги в місті з незалежного тракту: доба з такою тривогою не
    # може отримати «атаки не було» від каналу, який про неї просто не написав.
    # db.query віддає значення як рядки, а day — це datetime.date. Порівняння
    # date з рядком завжди дає «немає в множині», і запобіжник мовчки не
    # працює: рівно так 14 діб 2024 року з понад трьома годинами тривоги
    # отримали «атаки не було».
    long_alert = {str(r[0])[:10] for r in db.query(
        "SELECT raid_day FROM v_canon_daily "
        "WHERE region_code = 'kyiv_city' AND total_minutes >= 180")}

    obs = []
    for day, metrics in summaries.items():
        for metric, (value, ev) in metrics.items():
            obs.append((day, None, CHANNEL, "official", metric, "ua",
                        value, None, (ev or "")[:500]))
    for (day, metric, scope), (cnt, msg_id, sample) in tracks.items():
        obs.append((day, None, CHANNEL, "official", metric, scope,
                    cnt, msg_id, sample))
    # Свідченням удару ПО МІСТУ є лише треки міста. Треки області в лейбл
    # не входять — інакше ми знову назвали б Бровари Києвом.
    days_attacked = {d for (d, m, sc) in tracks if sc == "kyiv"}
    for day in days_attacked:
        obs.append((day, None, CHANNEL, "official", "attacked", "kyiv",
                    1, None, "є повідомлення супроводу цілей на Київ"))
    for day, n in alive.items():
        if (day not in days_attacked and n >= ALIVE_MIN
                and air.get(day, 0) >= AIR_MIN
                and day >= ZERO_FROM
                and day.isoformat() not in long_alert):
            obs.append((day, None, CHANNEL, "official", "attacked", "kyiv",
                        0, None, f"канал вів повітряну обстановку "
                                 f"({air.get(day, 0)} повідомлень з {n}), "
                                 f"жодного супроводу на Київ, "
                                 f"тривог у місті менше 3 годин"))

    write(obs)
    return n_sum, n_sum_parsed, n_track, len(obs)


def write(obs):
    if not obs:
        return
    city = int(db.scalar("SELECT id FROM regions WHERE code='kyiv_city'"))
    oblast = int(db.scalar("SELECT id FROM regions WHERE code='kyiv_oblast'"))
    rows = [(d, oblast if scope == "kyiv_obl" else city,
             src, tier, metric, scope, val, ev_id, ev_txt)
            for d, _r, src, tier, metric, scope, val, ev_id, ev_txt in obs]
    # Спершу знімаємо ВСЕ, що цей парсер писав раніше, і лише потім пишемо
    # заново. Самого upsert недостатньо: коли правило розбору стає суворішим,
    # частина старих рядків більше не відтворюється — і без видалення вони
    # тихо лишаються в базі як «спостереження», якого вже ніщо не підтверджує.
    db.sql("DELETE FROM attack_observations WHERE source = %s", (CHANNEL,))
    db.copy_upsert(
        "attack_observations",
        ["raid_day", "region_id", "source", "tier", "metric", "scope",
         "value", "evidence_msg_id", "evidence_text"],
        rows,
        conflict="raid_day, source, metric, scope",
        update=("value", "evidence_msg_id", "evidence_text", "extracted_at"))


if __name__ == "__main__":
    with db.Run("kpszsu_parse", "backfill", {"channel": CHANNEL}) as r:
        need, cur = db.parse_cursor("kpszsu_parse", CHANNEL)
        if "--force" in sys.argv:      # правила розбору змінились — перебрати все
            need = True
        if not need:
            r.skip(f"канал не виріс від минулого розбору (msg_id {cur})")
            print("  нових повідомлень немає — розбір пропущено")
            raise SystemExit(0)
        n_sum, n_parsed, n_track, n_obs = run()
        db.parse_done("kpszsu_parse", CHANNEL, cur, n_obs)
        r.rows_read, r.rows_written = n_sum + n_track, n_obs
        pct = 100 * n_parsed / n_sum if n_sum else 0
        print(f"  зведень {n_sum}, з них розібрано {n_parsed} ({pct:.0f}%), "
              f"повідомлень супроводу по Києву {n_track}, спостережень {n_obs}")
