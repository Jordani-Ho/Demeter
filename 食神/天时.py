#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""天时：给定一个地方和一个时刻，算出天时单。

对外只有一个函数：

    tianshi(lat, lon, tz, when) -> dict

when 是带时区的时刻，平常就是“现在”。返回的天时单照开发总纲第三节第 2 小节；
climate 不归天时管，这里不返回。

不带参数直接跑，打印湾区此刻的天时单，方便人看：

    python 食神/天时.py
"""

from datetime import datetime, timedelta, timezone
import json
import math
from zoneinfo import ZoneInfo

from lunar_python import Solar

# lunar_python 给的节气时刻是北京时间的钟面（UTC+8）
BEIJING = timezone(timedelta(hours=8))

# 三顿饭对应的时辰，以及它在真太阳时里的起点（小时）
MEALS = {
    "早": ("辰时", 7),
    "午": ("午时", 11),
    "晚": ("酉时", 17),
}

# 四季从四个“立”开始
SEASON_STARTS = {"立春": "春", "立夏": "夏", "立秋": "秋", "立冬": "冬"}

# 不带参数跑时用的地方：湾区
BAY_AREA = (37.33, -121.89, "America/Los_Angeles")


def _to_utc(solar):
    """把 lunar_python 的 Solar（北京时间的钟面）换成 UTC 时刻。"""
    moment = datetime(
        solar.getYear(),
        solar.getMonth(),
        solar.getDay(),
        solar.getHour(),
        solar.getMinute(),
        solar.getSecond(),
        tzinfo=BEIJING,
    )
    return moment.astimezone(timezone.utc)


def _solar_terms(around_year):
    """取一年前后的节气，返回按时间排好的 [(UTC 时刻, 节气名)]。

    一张表从上一年的冬至排到本年的 大雪，所以前后各取一年就够用了。
    """
    terms = {}
    for year in (around_year - 1, around_year, around_year + 1):
        table = Solar.fromYmd(year, 6, 1).getLunar().getJieQiTable()
        for name, solar in table.items():
            # 表里还有一份拼音大写的重复项，跳过
            if name.isascii():
                continue
            terms[_to_utc(solar)] = name
    return sorted(terms.items())


def _term_borders(terms, when_utc):
    """当地此刻以前最近的那个节气，和下一个节气。"""
    previous = None
    following = None
    for at, name in terms:
        if at <= when_utc:
            previous = (at, name)
        else:
            following = (at, name)
            break
    if previous is None or following is None:
        raise ValueError("时刻离得太远，算不出前后节气：{}".format(when_utc))
    return previous, following


def _season(terms, when_utc):
    """立春到立夏以前是春，立夏到立秋以前是夏，依此类推。"""
    latest = None
    for at, name in terms:
        if at <= when_utc and name in SEASON_STARTS:
            latest = name
    if latest is None:
        raise ValueError("时刻离得太远，算不出季节：{}".format(when_utc))
    return SEASON_STARTS[latest]


def _equation_of_time(when_utc):
    """均时差（分钟）：真太阳时 = 平太阳时 + 均时差。

    用天文学年历里常见的近似公式（NOAA 那套），一年内的误差在半分钟以内。
    """
    day_of_year = when_utc.timetuple().tm_yday
    hour = when_utc.hour + when_utc.minute / 60
    gamma = 2 * math.pi / 365 * (day_of_year - 1 + (hour - 12) / 24)
    return 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )


def _hhmm(minutes):
    """一天里的第几分钟换成钟表上的 HH:MM。"""
    minutes = round(minutes) % (24 * 60)
    return "{:02d}:{:02d}".format(int(minutes) // 60, int(minutes) % 60)


def _meals(lon, local, when_utc):
    """早、午、晚三顿：时辰按真太阳时算，clock 换回当地钟表。

    真太阳时 = UTC + 经度 ÷ 15 小时 + 均时差；
    所以钟表时间 = 真太阳时 − 经度 ÷ 15 小时 − 均时差 + 当地时区偏移。
    """
    equation = _equation_of_time(when_utc)
    longitude_minutes = lon / 15 * 60
    zone_minutes = local.utcoffset().total_seconds() / 60

    meals = {}
    for name, (shichen, start_hour) in MEALS.items():
        start = start_hour * 60 - longitude_minutes - equation + zone_minutes
        meals[name] = {
            "shichen": shichen,
            "clock": "{}-{}".format(_hhmm(start), _hhmm(start + 120)),
        }
    return meals


def _almanac(local):
    """当地日期的干支日，以及黄历的宜、忌。"""
    lunar = Solar.fromYmd(local.year, local.month, local.day).getLunar()
    return {
        "ganzhi_day": lunar.getDayInGanZhi(),
        "yi": lunar.getDayYi(),
        "ji": lunar.getDayJi(),
    }


def tianshi(lat: float, lon: float, tz: str, when: datetime) -> dict:
    """算一张天时单。

    lat、lon 是纬度、经度（东经为正）；tz 是 IANA 时区名，例如 America/Los_Angeles；
    when 是带时区的时刻。
    """
    if when.tzinfo is None:
        raise ValueError("when 必须是带时区的时刻")
    tzinfo = ZoneInfo(tz)
    when_utc = when.astimezone(timezone.utc)
    local = when.astimezone(tzinfo)

    terms = _solar_terms(local.year)
    previous, following = _term_borders(terms, when_utc)

    return {
        "date": local.date().isoformat(),
        "place": {"lat": lat, "lon": lon, "tz": tz},
        "solar_term": previous[1],
        "next_solar_term": {
            "name": following[1],
            "at": following[0].astimezone(tzinfo).isoformat(timespec="seconds"),
        },
        "season": _season(terms, when_utc),
        "almanac": _almanac(local),
        "meals": _meals(lon, local, when_utc),
    }


def main():
    """不带参数跑时，打印湾区此刻的天时单。"""
    result = tianshi(*BAY_AREA, datetime.now(timezone.utc))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
