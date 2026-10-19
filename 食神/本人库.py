#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本人库：主人和主人照看的人的资料，就一个 JSON 文件。

放哪由环境变量 SHISHEN_HOME 决定，默认是仓库根目录下的 我的食神/；文件名是 本人库.json。
我的食神/ 在 .gitignore 里：主人的真实资料不进仓库。

对外三个函数：

    load() -> dict
    save(data) -> None
    apply(data, changes) -> (新的 data, 被挡下的改动和理由)

另有两个给“记”用的小工具：

    load_word_list() -> dict        # 词表全文
    bencao_names() -> dict          # 本草 id -> 中文名
"""

import copy
from datetime import datetime
import json
import os
import tempfile
from zoneinfo import ZoneInfo

# 仓库根：本文件在 <根>/食神/ 下
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCAO_DIR = os.path.join(ROOT, "本草库")
WORD_LIST = os.path.join(BENCAO_DIR, "词表.json")
DEFAULT_HOME = os.path.join(ROOT, "我的食神")
FILE_NAME = "本人库.json"

# set 能改的项
SET_FIELDS = ("name", "birth_year", "constitution", "taste", "avoid")


def home():
    """本人库放在哪个文件夹：SHISHEN_HOME，没设就用仓库下的 我的食神/。"""
    return os.environ.get("SHISHEN_HOME") or DEFAULT_HOME


def path():
    """本人库文件的完整路径。"""
    return os.path.join(home(), FILE_NAME)


def empty():
    """一份空本人库，照开发总纲第三节第 1 小节。"""
    return {
        "owner": "主人",
        "place": {},
        "people": [],
        "feelings": [],
        "saved": [],
        "pantry": [],
        "history": [],
    }


def load():
    """读本人库；文件还没有，就给一份空的。"""
    file_path = path()
    if not os.path.exists(file_path):
        return empty()
    with open(file_path, encoding="utf-8-sig") as handle:
        return json.load(handle)


def save(data):
    """写本人库。先写临时文件再改名，写到一半坏了也不会把原来的冲掉。"""
    file_path = path()
    directory = os.path.dirname(file_path)
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".本人库-", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, file_path)
    except BaseException:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise


def load_word_list():
    """读词表全文（体质、偏向、性、味）。"""
    with open(WORD_LIST, encoding="utf-8-sig") as handle:
        return json.load(handle)


def bencao_names():
    """本草库里的 id 到中文名的对照，词表.json 不算条目。"""
    names = {}
    if not os.path.isdir(BENCAO_DIR):
        return names
    for filename in sorted(os.listdir(BENCAO_DIR)):
        if not filename.endswith(".json") or filename == "词表.json":
            continue
        with open(os.path.join(BENCAO_DIR, filename), encoding="utf-8-sig") as handle:
            entry = json.load(handle)
        entry_id = entry.get("id")
        if isinstance(entry_id, str):
            names[entry_id] = entry.get("name", entry_id)
    return names


def now_at(data):
    """当地时刻，ISO 8601，带时区偏移。"""
    place = data.get("place")
    tz_name = place.get("tz") if isinstance(place, dict) else None
    if isinstance(tz_name, str) and tz_name:
        try:
            return datetime.now(ZoneInfo(tz_name)).isoformat(timespec="seconds")
        except (KeyError, ValueError):
            pass
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_string_list(value):
    return isinstance(value, list) and all(
        isinstance(item, str) and item.strip() for item in value
    )


def _find_person(data, reference):
    """按 id 或 name 找一个人。"""
    if not isinstance(reference, str) or not reference.strip():
        return None
    for person in data.get("people", []):
        if person.get("id") == reference or person.get("name") == reference:
            return person
    return None


def _next_person_id(people):
    used = {person.get("id") for person in people}
    index = 1
    while "p{}".format(index) in used:
        index += 1
    return "p{}".format(index)


def _apply_one(data, change, allowed_constitution, allowed_items):
    """做一条改动。做成了返回 None，挡下了返回理由。"""
    if not isinstance(change, dict):
        return "改动要是对象"
    op = change.get("op")
    at = now_at(data)

    if op == "add_person":
        name = change.get("name")
        if not isinstance(name, str) or not name.strip():
            return "add_person 要有 name"
        if any(person.get("name") == name for person in data["people"]):
            return "已经有叫“{}”的人，改这个人请用 set".format(name)
        person = {
            "id": _next_person_id(data["people"]),
            "name": name,
            "constitution": [],
            "taste": [],
            "avoid": [],
            "notes": [],
            "at": at,
        }
        birth_year = change.get("birth_year")
        if birth_year is not None:
            if not isinstance(birth_year, int) or isinstance(birth_year, bool):
                return "birth_year 要是整数"
            person["birth_year"] = birth_year
        data["people"].append(person)
        return None

    if op == "set":
        person = _find_person(data, change.get("person"))
        if person is None:
            return "找不到这个人：{}".format(change.get("person"))
        field = change.get("field")
        if field not in SET_FIELDS:
            return "set 不能改“{}”，只能改 {}".format(field, "、".join(SET_FIELDS))
        value = change.get("value")
        if field == "name":
            if not isinstance(value, str) or not value.strip():
                return "name 要是非空字符串"
        elif field == "birth_year":
            if not isinstance(value, int) or isinstance(value, bool):
                return "birth_year 要是整数"
        elif field == "constitution":
            if not _is_string_list(value):
                return "constitution 要是字符串数组"
            strange = [word for word in value if word not in allowed_constitution]
            if strange:
                return "这些词不在词表的体质或偏向里：{}".format("、".join(strange))
        else:  # taste、avoid
            if not _is_string_list(value):
                return "{} 要是字符串数组".format(field)
        person[field] = value
        person["at"] = at
        return None

    if op == "note":
        person = _find_person(data, change.get("person"))
        if person is None:
            return "找不到这个人：{}".format(change.get("person"))
        text = change.get("text")
        if not isinstance(text, str) or not text.strip():
            return "note 要有 text"
        person.setdefault("notes", []).append({"at": at, "text": text})
        return None

    if op == "place":
        name = change.get("name")
        latitude = change.get("lat")
        longitude = change.get("lon")
        tz_name = change.get("tz")
        if not isinstance(name, str) or not name.strip():
            return "place 要有 name"
        for key, value, low, high in (
            ("lat", latitude, -90, 90),
            ("lon", longitude, -180, 180),
        ):
            if not _is_number(value) or not low <= value <= high:
                return "place 的 {} 要是 {} 到 {} 之间的数".format(key, low, high)
        if not isinstance(tz_name, str) or not tz_name.strip():
            return "place 要有 tz"
        try:
            ZoneInfo(tz_name)
        except (KeyError, ValueError):
            return "tz 不是合法的时区名：{}".format(tz_name)
        place = {
            "name": name,
            "lat": latitude,
            "lon": longitude,
            "tz": tz_name,
            "at": at,
        }
        region = change.get("region")
        if region is not None:
            if not isinstance(region, str):
                return "region 要是字符串"
            place["region"] = region
        climate = change.get("climate")
        if climate is not None:
            if not isinstance(climate, dict):
                return "climate 要是对象"
            place["climate"] = climate
        data["place"] = place
        return None

    if op == "pantry":
        item = change.get("item")
        if not isinstance(item, str) or not item.strip():
            return "pantry 要有 item"
        if item not in allowed_items:
            return "本草库里没有这味料：{}".format(item)
        qty = change.get("qty")
        unit = change.get("unit")
        if not _is_number(qty) or qty <= 0:
            return "pantry 的 qty 要是大于 0 的数"
        if not isinstance(unit, str) or not unit.strip():
            return "pantry 要有 unit"
        for entry in data["pantry"]:
            if entry.get("item") == item:
                entry["qty"] = qty
                entry["unit"] = unit
                entry["at"] = at
                break
        else:
            data["pantry"].append(
                {"item": item, "qty": qty, "unit": unit, "at": at}
            )
        return None

    return "不认识的 op：{}".format(op)


def apply(data, changes):
    """把一串改动写进本人库。

    改动合格的照做，不合格的挡下。返回 (新的 data, 被挡下的 [(改动, 理由)])；
    传进来的 data 不会被改。
    """
    result = copy.deepcopy(data) if isinstance(data, dict) else empty()
    result.setdefault("owner", "主人")
    result.setdefault("place", {})
    for key in ("people", "feelings", "saved", "pantry", "history"):
        result.setdefault(key, [])

    if not isinstance(changes, list):
        return result, [(changes, "改动要是数组")]

    words = load_word_list()
    allowed_constitution = set(words["体质"]) | set(words["偏向"])
    allowed_items = set(bencao_names())

    blocked = []
    for change in changes:
        reason = _apply_one(result, change, allowed_constitution, allowed_items)
        if reason:
            blocked.append((change, reason))
    return result, blocked
