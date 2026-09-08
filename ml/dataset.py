"""Навчальна матриця: один рядок = одна доба нальоту (12:00 -> 12:00 Київ).

Правило, з якого все випливає: відсічка прогнозу — 12:00 доби d, тобто рівно
початок вікна. Отже будь-яка ознака має бути функцією рядків із raid_day <= d-1.
Реалізовано через shift(1) на цільових рядах: жодна колонка не бачить свого дня.
"""
import os
import numpy as np
import pandas as pd
import psycopg

DB = os.environ.get("DATABASE_URL", "postgresql://missiles:missiles@127.0.0.1:5543/missiles")

# 2024 — початок повного режиму розмітки (див. docs/METHODOLOGY.md §3).
# Раніший період має лейбли, виведені лише з тривог, і змішувати їх не можна.
TRAIN_START = "2024-01-01"

# Ряди, з яких будуються історичні вікна
HIST = ["y_attacked_i", "y_alert_minutes", "y_drone_tracks", "y_missile_tracks",
        # цілі над областю: не лейбл, але відомі до відсічки й географічно
        # ближчі до міста, ніж національні числа
        "y_drone_tracks_obl"]

BLOCK_A = ["alerts_prev", "alert_minutes_prev", "drone_tracks_prev", "missile_tracks_prev",
           "drone_tracks_obl_prev", "missile_tracks_obl_prev",
           "drones_launched_ua_prev", "mig31k_prev", "strategic_prev", "kalibr_prev"]
BLOCK_C = ["dow_sin", "dow_cos", "month_sin", "month_cos", "night_hours",
           "heating_season", "holiday_ua_w", "holiday_ru_w"]
BLOCK_D = ["night_cloud_low_avg", "night_wind_avg", "night_temp_avg", "night_precip_sum"]


def load_raw(future_days: int = 0) -> pd.DataFrame:
    """Сира v_daily_features.

    Пастка: календар доведено до 2027, і майбутні доби лежать у представленні
    з y_attacked = false. Без відсічки по current_date модель навчиться на
    сотнях фальшивих «тихих» діб.

    future_days > 0 впускає рівно стільки майбутніх діб, скільки потрібно для
    ПРОГНОЗУ (рядок ознак на завтра). Їхні колонки y_* — сміття, тому в
    навчальну вибірку вони не потрапляють: за це відповідає окремий фільтр
    у final._daily_one, а не цей запит.
    """
    with psycopg.connect(DB) as conn:
        cur = conn.execute(
            "SELECT * FROM v_daily_features "
            "WHERE raid_day >= %s AND raid_day <= current_date + %s ORDER BY raid_day",
            (TRAIN_START, future_days))
        cols = [d[0] for d in cur.description]
        df = pd.DataFrame(cur.fetchall(), columns=cols)

    df["raid_day"] = pd.to_datetime(df["raid_day"])
    # Доби без жодного твердження джерела (y_attacked IS NULL) — це не «атаки
    # не було». Але викидати їх ТУТ не можна: ознаки будуються позиційним
    # зсувом, і дірка в ряді зробила б «вчора» позавчорашнім. Тому позначаємо
    # прапорцем, будуємо ознаки на суцільному ряді, а відкидаємо вже перед
    # навчанням — за y_known.
    df["y_known"] = df["y_attacked"].notna()
    df["y_attacked_i"] = df["y_attacked"].fillna(False).astype(int)
    df["heating_season"] = df["heating_season"].astype(int)
    for c in df.columns:
        if c not in ("raid_day", "y_attacked", "holiday_ua", "holiday_ru"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("raid_day").reset_index(drop=True)


def add_features(df: pd.DataFrame, lag: int = 1) -> pd.DataFrame:
    """Блок B: історичні вікна.

    lag=1 — прогноз на добу, що починається сьогодні о 12:00 («сьогодні»).
    lag=2 — прогноз на наступну добу нальоту («завтра»): на момент відсічки
    доба d-1 ще не закінчилась, тому останнє повністю відоме — це d-2.
    Плутанина тут коштує витоку, який виглядає як геніальна модель.
    """
    d = df.copy()

    # календар у циклічному вигляді: для лінійних моделей і kNN грудень і січень
    # мають бути поруч, а як цілі числа 12 і 1 вони на різних кінцях шкали
    d["dow_sin"] = np.sin(2 * np.pi * d["dow"] / 7)
    d["dow_cos"] = np.cos(2 * np.pi * d["dow"] / 7)
    d["month_sin"] = np.sin(2 * np.pi * d["month"] / 12)
    d["month_cos"] = np.cos(2 * np.pi * d["month"] / 12)

    # БЛОК A. У поданні ці колонки жорстко визначені як доба d-1
    # (012_features.sql: JOIN ... ON pl.raid_day = c.day - 1). Для lag=1 це
    # правильно: доба d-1 закривається рівно о 12:00 доби d, тобто на відсічці.
    # Для lag=2 відсічка — 12:00 доби d-1, тобто ПОЧАТОК того самого вікна:
    # уся доба d-1 ще попереду. Тому блок A треба додатково зсунути на lag-1.
    # Без цього горизонт «завтра» читав добу, якої на відсічці ще не існує, і
    # виглядав майже так само добре, як «сьогодні» — це був артефакт, не якість.
    if lag > 1:
        for c in BLOCK_A:
            d[c] = d[c].shift(lag - 1)

    made = []
    for c in HIST:
        s = d[c].shift(lag)                     # усе, що відоме до відсічки
        d[f"{c}_l1"] = s
        d[f"{c}_l2"] = d[c].shift(lag + 1)
        d[f"{c}_l3"] = d[c].shift(lag + 2)
        made += [f"{c}_l1", f"{c}_l2", f"{c}_l3"]
        for w in (3, 7, 14, 30):
            d[f"{c}_m{w}"] = s.rolling(w, min_periods=max(2, w // 3)).mean()
            made.append(f"{c}_m{w}")
        d[f"{c}_sd7"] = s.rolling(7, min_periods=3).std()
        d[f"{c}_max7"] = s.rolling(7, min_periods=3).max()
        d[f"{c}_ewm"] = s.ewm(alpha=0.3, min_periods=3).mean()
        made += [f"{c}_sd7", f"{c}_max7", f"{c}_ewm"]

    # довжина поточної серії однакових діб і скільки минуло від сильної доби
    prev = d["y_attacked_i"].shift(lag)
    grp = (prev != prev.shift(1)).cumsum()
    d["streak_prev"] = prev.groupby(grp).cumcount() + 1
    # Поріг «сильної доби» той самий, що й у означенні масованої атаки
    # (MASSIVE_TRACKS): дві різні магічні константи на одному ряді означали б,
    # що ознака й лейбл говорять про різні події.
    strong = (d["y_drone_tracks"].shift(lag) >= MASSIVE_TRACKS)
    idx = pd.Series(np.arange(len(d)), index=d.index)
    d["days_since_strong"] = (idx - idx.where(strong).ffill()).fillna(999)
    made += ["streak_prev", "days_since_strong"]

    d.attrs["block_b"] = made
    return d


MASSIVE_MINUTES = 480      # 8 годин під тривогою за добу нальоту
MASSIVE_TRACKS = 15        # або надзвичайно щільний супровід цілей


def add_labels(df: pd.DataFrame, split_idx: int | None = None) -> pd.DataFrame:
    """Порядкова шкала тяжкості 0-3 (docs/METHODOLOGY.md §2).

    Рівень 3 («масована атака») спирається на ТРИВАЛІСТЬ ТРИВОГ, а не на
    кількість треків. Причина: треки — це кількість повідомлень каналу, і вона
    росте разом із його балакучістю. Q90 треків у добу атаки: 5 (2024), 5
    (2025), 9 (2026), максимум 10 → 21 → 38. Поріг, знятий з одного року,
    наступного означає вже інше. Хвилини тривог приходять із реєстру КМДА —
    окремого тракту, який від каналу не залежить узагалі.

    Поріг 8 годин під тривогою за добу нальоту дає 6 / 14 / 11 діб на рік:
    рідкісна подія, яка збігається з тим, що місто називає важкою ніччю.
    """
    d = df.copy()
    tracks = d["y_drone_tracks"] + d["y_missile_tracks"]
    S = np.zeros(len(d), dtype=int)
    S[(d["y_alert_minutes"] >= 30).values] = 1          # тривога без ознак цілей
    S[(tracks > 0).values] = 2                          # цілі на місто
    massive = ((d["y_alert_minutes"] >= MASSIVE_MINUTES)
               | (d["y_drone_tracks"] >= MASSIVE_TRACKS))
    S[(massive & (tracks > 0)).values] = 3              # масована атака
    d["S"] = S
    d["S_ge1"] = (S >= 1).astype(int)
    # S_ge2 тотожна y_attacked за побудовою (лейбл «атака» = треки > 0),
    # тому окремої цілі з неї не робимо — це був би дубль.
    d["S_ge3"] = (S >= 3).astype(int)
    # split_idx лишається в сигнатурі для сумісності, але пороги свідомо
    # АПРІОРНІ, а не квантильні: квантиль треків дрейфує разом із балакучістю
    # каналу (q90 у добу атаки: 5 / 5 / 9 по роках), і лейбл, порахований
    # квантилем, означав би різне в різні роки.
    d.attrs["thresholds"] = {"minutes": MASSIVE_MINUTES, "tracks": MASSIVE_TRACKS,
                             "апріорні": True}
    return d


def build(weather: bool = True, lag: int = 1, future_days: int = 0):
    """Повертає (df, feature_blocks). weather=False прибирає блок D (витік)."""
    d = add_features(load_raw(future_days), lag=lag)
    blocks = {"A_prev": BLOCK_A, "B_hist": d.attrs["block_b"], "C_calendar": BLOCK_C}
    if weather:
        blocks["D_weather"] = BLOCK_D
    # перші 30 рядків мають неповні вікна — відрізаємо, щоб не імпутувати наосліп
    d = d.iloc[30:].reset_index(drop=True)
    n = len(d)
    d = d[d["y_known"]].reset_index(drop=True)   # лейбл невідомий -> не вчимось
    if n - len(d):
        print(f"  dataset: {n - len(d)} діб без лейбла відкинуто ПІСЛЯ побудови ознак")
    return d, blocks
