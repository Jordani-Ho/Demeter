#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抽参：把本人库和天时单抽成一张参数单，只留需要的。

对外一个函数：

    chouchan(data, tianshi_dan, days=7, meals=("午", "晚"), drinks=True, who=None) -> dict

- data 是本人库，tianshi_dan 是天时单，返回的参数单照开发总纲第三节第 3 小节。
- who 是要照看的人的 id 列表；不给就是本人库里的所有人。
- 每个人给一个代号：甲、乙、丙…… 顺序跟 who 一样。

参数单里只能出现白名单里的键。组装完对着白名单再查一遍，多出任何一个键就报错，
不悄悄删掉。
"""

import secrets

# 参数单的白名单：多一个键都不行
WHITELIST = {
    "request_id": None,
    "range": {"days", "meals", "drinks"},
    "people": {"tag", "age_band", "constitution", "taste", "avoid"},
    "tianshi": {"solar_term", "season", "almanac_ji"},
    "di": {"climate", "region"},
}

TAGS = "甲乙丙丁戊己庚辛壬癸"

# (下限, 上限, 名字)；上限为 None 表示再往上都是这一档
AGE_BANDS = (
    (0, 5, "幼儿"),
    (6, 17, "少年"),
    (18, 39, "青年"),
    (40, 64, "中年"),
    (65, 84, "老年"),
    (85, None, "高龄"),
)


def tag(index):
    """第几个人叫什么代号。超过十个用天干加轮次：甲、乙……癸、甲2、乙2……"""
    if index < len(TAGS):
        return TAGS[index]
    return TAGS[index % len(TAGS)] + str(index // len(TAGS) + 1)


def age_band(birth_year, year):
    """年龄只给年龄段；出生年不知道、或者算出负数，都不给。"""
    if not isinstance(birth_year, int) or isinstance(birth_year, bool):
        return None
    age = year - birth_year
    if age < 0:
        return None
    for lower, upper, name in AGE_BANDS:
        if age >= lower and (upper is None or age <= upper):
            return name
    return None


def _check_whitelist(canshu):
    """参数单里多出白名单以外的键就报错。"""
    extra = []

    def collect(prefix, value, allowed):
        if not isinstance(value, dict):
            return
        for key in value:
            if key not in allowed:
                extra.append(prefix + key)

    collect("", canshu, WHITELIST)
    collect("range.", canshu.get("range"), WHITELIST["range"])
    collect("tianshi.", canshu.get("tianshi"), WHITELIST["tianshi"])
    collect("di.", canshu.get("di"), WHITELIST["di"])
    people = canshu.get("people")
    if isinstance(people, list):
        for index, person in enumerate(people):
            collect("people[{}].".format(index), person, WHITELIST["people"])

    if extra:
        raise ValueError(
            "参数单里有多余的键：{}（白名单以外的键一律不出本人库）".format(
                "、".join(sorted(extra))
            )
        )


def _choose_people(data, who):
    people = data.get("people") or []
    if who is None:
        return list(people)

    by_id = {person.get("id"): person for person in people}
    chosen = []
    for person_id in who:
        person = by_id.get(person_id)
        if person is None:
            raise ValueError("who 里有找不到的人：{}".format(person_id))
        chosen.append(person)
    return chosen


def chouchan(
    data: dict,
    tianshi_dan: dict,
    days: int = 7,
    meals=("午", "晚"),
    drinks: bool = True,
    who=None,
) -> dict:
    """本人库 + 天时单 -> 参数单。"""
    year = int(str(tianshi_dan.get("date", ""))[:4]) if tianshi_dan.get("date") else None
    chosen = _choose_people(data, who)

    people = []
    for index, person in enumerate(chosen):
        item = {
            "tag": tag(index),
            "constitution": list(person.get("constitution") or []),
            "taste": list(person.get("taste") or []),
            "avoid": list(person.get("avoid") or []),
        }
        band = age_band(person.get("birth_year"), year) if year else None
        if band:
            item["age_band"] = band
        people.append(item)

    place = data.get("place") or {}
    almanac = tianshi_dan.get("almanac") or {}
    canshu = {
        "request_id": secrets.token_hex(8),
        "range": {"days": days, "meals": list(meals), "drinks": drinks},
        "people": people,
        "tianshi": {
            "solar_term": tianshi_dan.get("solar_term"),
            "season": tianshi_dan.get("season"),
            "almanac_ji": list(almanac.get("ji") or []),
        },
        "di": {},
    }
    if "region" in place:
        canshu["di"]["region"] = place["region"]
    if "climate" in place:
        canshu["di"]["climate"] = place["climate"]

    _check_whitelist(canshu)
    return canshu
