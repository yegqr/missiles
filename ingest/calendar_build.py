#!/usr/bin/env python3
"""Календар: свята, тривалість ночі, опалювальний сезон.

Українські й російські дати тримаємо в РІЗНИХ колонках. Змішувати не можна:
гіпотези протилежні за напрямком. Українські свята — привід для демонстративного
удару по нас; російські — привід відзвітувати «перемогою», і теж підвищують
ризик, але з іншої причини й з іншим часовим профілем.

Рухомі дати рахуються, а не забиваються руками: православний Великдень —
за юліанською пасхалією. Різдво в Україні з 2023 року офіційно 25 грудня,
до того 7 січня — цю зміну враховано, інакше в даних буде зсув на два тижні.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db

START, END = date(2022, 1, 1), date(2027, 12, 31)
KYIV_LAT = 50.4501


def orthodox_easter(year):
    """Юліанська пасхалія, переведена у григоріанський календар."""
    a, b, c = year % 4, year % 7, year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month = (d + e + 114) // 31
    day = ((d + e + 114) % 31) + 1
    julian = date(year, month, day)
    return julian + timedelta(days=13)      # зсув для XXI століття


def ua_holidays(year):
    """-> {дата: (назва, вага 1..3)}"""
    e = orthodox_easter(year)
    h = {
        date(year, 1, 1):   ("Новий рік", 3),
        date(year, 1, 22):  ("День Соборності", 2),
        date(year, 2, 24):  ("Річниця вторгнення", 3),
        date(year, 3, 8):   ("8 березня", 1),
        date(year, 5, 8):   ("День памʼяті та перемоги", 2),
        date(year, 6, 28):  ("День Конституції", 2),
        # День Державності запроваджено 2021 на 28 липня; з 2023 перенесено
        # на 15 липня. Одна фіксована дата для всіх років ставить свято не
        # туди рівно в 2022 — найінтенсивніший рік війни.
        date(year, 7, 15) if year >= 2023 else date(year, 7, 28):
                            ("День Державності", 2),
        date(year, 8, 23):  ("День Прапора", 2),
        date(year, 8, 24):  ("День Незалежності", 3),
        # До 2023 День захисників відзначався 14 жовтня (Покрова), з 2023 — 1 жовтня
        date(year, 10, 1) if year >= 2023 else date(year, 10, 14):
                            ("День захисників і захисниць", 2),
        date(year, 12, 6):  ("День Збройних Сил", 2),
        e:                  ("Великдень", 3),
        # Трійця (П'ятидесятниця) — Великдень + 49 днів, а не 50: сам Великдень
        # рахується першим днем. Зсув на добу був у ВСІХ роках.
        e + timedelta(49):  ("Трійця", 1),
    }
    # Різдво: з 2023 ОЦУ перейшла на 25 грудня
    if year >= 2023:
        h[date(year, 12, 25)] = ("Різдво", 3)
    else:
        h[date(year, 1, 7)] = ("Різдво", 3)
        h[date(year, 12, 25)] = ("Різдво (західне)", 1)
    return h


def ru_holidays(year):
    e = orthodox_easter(year)
    return {
        date(year, 1, 1):   ("Новий рік", 2),
        date(year, 1, 7):   ("Різдво (РПЦ)", 2),
        date(year, 2, 23):  ("День захисника вітчизни", 3),
        date(year, 3, 8):   ("8 березня", 1),
        date(year, 4, 12):  ("День космонавтики", 1),
        date(year, 5, 1):   ("1 травня", 1),
        date(year, 5, 9):   ("День перемоги", 3),
        date(year, 6, 12):  ("День росії", 2),
        date(year, 8, 2):   ("День ВДВ", 1),
        date(year, 11, 4):  ("День єдності", 2),
        date(year, 12, 12): ("День конституції рф", 1),
        e:                  ("Пасха (РПЦ)", 2),
    }


def night_hours(d, lat=KYIV_LAT):
    """Тривалість темного часу, годин. Проста сонячна геометрія."""
    import math
    n = d.timetuple().tm_yday
    decl = 23.44 * math.sin(math.radians(360 / 365 * (n - 81)))
    x = -math.tan(math.radians(lat)) * math.tan(math.radians(decl))
    x = max(-1.0, min(1.0, x))
    day_h = 2 * math.degrees(math.acos(x)) / 15
    return round(24 - day_h, 2)


def run():
    rows = []
    for year in range(START.year, END.year + 1):
        ua, ru = ua_holidays(year), ru_holidays(year)
        d = max(date(year, 1, 1), START)
        last = min(date(year, 12, 31), END)
        while d <= last:
            hu = ua.get(d)
            hr = ru.get(d)
            rows.append((
                d, d.isoweekday(), d.month,
                hu[0] if hu else None, hu[1] if hu else None,
                hr[0] if hr else None, hr[1] if hr else None,
                night_hours(d),
                # Опалювальний сезон в Україні ≈ 15.10 - 15.04, а не «жовтень-березень»:
                # перша половина жовтня хибно потрапляла в сезон, перша половина
                # квітня хибно з нього випадала.
                ((d.month, d.day) >= (10, 15)) or ((d.month, d.day) <= (4, 15)),
            ))
            d += timedelta(days=1)
    db.sql("TRUNCATE calendar_days")
    db.copy_rows("calendar_days",
                 ["day", "dow", "month", "holiday_ua", "holiday_ua_w",
                  "holiday_ru", "holiday_ru_w", "night_hours", "heating_season"],
                 rows)
    return len(rows)


if __name__ == "__main__":
    with db.Run("calendar", "backfill", {}) as r:
        n = run()
        r.rows_read = r.rows_written = n
        print(f"  діб у календарі: {n}")
