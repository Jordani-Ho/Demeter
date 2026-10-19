#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""插口：装上厨神，检查它守不守律，替食神和它说话。

对外两个函数：

    load(path) -> 厨神                      # 装上一个厨神；说明书不合格就报错
    ask(厨神, canshu, llm) -> (合格的方案列表, 被丢掉的方案和理由)

照开发总纲第四节：
- 只把参数单的深拷贝和 llm 传给厨神的 teach，别的什么都不传。
- 回来的方案逐个检查，一个方案有一处不过就整个丢掉，理由记下来。
- 厨神抛异常、超时（默认 60 秒）、回来的不是 JSON 对象，都当作一个合格方案都没有。
"""

import copy
import importlib.util
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCAO_DIR = os.path.join(ROOT, "本草库")
BANNED_PATH = os.path.join(ROOT, "食神", "禁词.json")

SKILL_FIELDS = ("name", "kind", "author", "entry", "reads", "writes", "knowledge")
BASIC_KINDS = ("食材", "药食同源", "调料", "茶饮")
METHODS = ("煎", "炒", "焖", "炸", "焗", "蒸", "煮", "煲", "炖", "泡", "生食")
DISH_KINDS = ("汤", "菜", "主食", "粥", "点心")
TIMEOUT = 60


class 厨神:
    """装上来的一个厨神：说明书、入口函数、文件夹。"""

    def __init__(self, path, skill, teach):
        self.path = path
        self.skill = skill
        self.teach = teach

    @property
    def name(self):
        return self.skill.get("name")


def _check_skill(skill, folder):
    """说明书要老实：字段齐全，kind 是厨神，reads/writes 只有参数单和方案。"""
    if not isinstance(skill, dict):
        raise ValueError("skill.json 要是 JSON 对象")
    missing = [field for field in SKILL_FIELDS if field not in skill]
    if missing:
        raise ValueError("skill.json 缺字段：{}".format("、".join(missing)))
    for field in ("name", "kind", "author", "entry"):
        value = skill[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError("skill.json 的 {} 要是非空字符串".format(field))
    for field in ("reads", "writes", "knowledge"):
        value = skill[field]
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            raise ValueError("skill.json 的 {} 要是字符串数组".format(field))
    if skill["kind"] != "厨神":
        raise ValueError(
            "skill.json 的 kind 要是“厨神”，现在是“{}”".format(skill["kind"])
        )
    if skill["reads"] != ["参数单"]:
        raise ValueError(
            "skill.json 的 reads 只能有“参数单”，现在的 reads 是：{}".format(
                skill["reads"]
            )
        )
    if skill["writes"] != ["方案"]:
        raise ValueError(
            "skill.json 的 writes 只能有“方案”，现在的 writes 是：{}".format(
                skill["writes"]
            )
        )


def _load_module(entry_path):
    module_name = "shishen_chef_" + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(module_name, entry_path)
    if spec is None or spec.loader is None:
        raise ValueError("入口文件加载不了：{}".format(entry_path))
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise ValueError("入口文件 import 失败：{}：{}".format(entry_path, exc)) from exc
    return module


def load(path):
    """装上一个厨神。说明书不合格就报错，说清哪里不对。"""
    folder = os.path.abspath(path)
    if not os.path.isdir(folder):
        raise ValueError("厨神文件夹不存在：{}".format(path))

    skill_path = os.path.join(folder, "skill.json")
    try:
        with open(skill_path, encoding="utf-8-sig") as handle:
            skill = json.load(handle)
    except OSError as exc:
        raise ValueError("读不了 skill.json：{}".format(exc)) from exc
    except json.JSONDecodeError as exc:
        raise ValueError("skill.json 不是合法 JSON：{}".format(exc)) from exc

    _check_skill(skill, folder)

    entry_path = os.path.join(folder, skill["entry"])
    if not os.path.isfile(entry_path):
        raise ValueError("入口文件不存在：{}".format(skill["entry"]))
    module = _load_module(entry_path)
    teach = getattr(module, "teach", None)
    if not callable(teach):
        raise ValueError("入口 {} 里没有 teach 函数".format(skill["entry"]))

    return 厨神(folder, skill, teach)


def _bencao():
    """本草库：id -> 条目。词表.json 不是条目。"""
    entries = {}
    if not os.path.isdir(BENCAO_DIR):
        return entries
    for filename in sorted(os.listdir(BENCAO_DIR)):
        if not filename.endswith(".json") or filename == "词表.json":
            continue
        with open(os.path.join(BENCAO_DIR, filename), encoding="utf-8-sig") as handle:
            entry = json.load(handle)
        if isinstance(entry.get("id"), str):
            entries[entry["id"]] = entry
    return entries


def _banned_words():
    try:
        with open(BANNED_PATH, encoding="utf-8-sig") as handle:
            words = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []
    return [word for word in words if isinstance(word, str) and word]


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _visible_texts(item):
    """给人看的文字：name、steps、why、when，以及料的 name。"""
    for field in ("name", "steps", "why", "when"):
        value = item.get(field)
        if isinstance(value, str):
            yield value
    for ingredient in item.get("ingredients") or []:
        if isinstance(ingredient, dict):
            name = ingredient.get("name")
            if isinstance(name, str):
                yield name


def _find_banned(plan, banned):
    """只在给人看的文字里按字面包含查禁词：idea、name（含料的 name）、steps、why、when。"""
    texts = []
    if isinstance(plan.get("idea"), str):
        texts.append(plan["idea"])
    for day in plan.get("days") or []:
        if not isinstance(day, dict):
            continue
        for meal in day.get("meals") or []:
            if not isinstance(meal, dict):
                continue
            for dish in meal.get("dishes") or []:
                if isinstance(dish, dict):
                    texts.extend(_visible_texts(dish))
        for drink in day.get("drinks") or []:
            if isinstance(drink, dict):
                texts.extend(_visible_texts(drink))
    for text in texts:
        for word in banned:
            if word in text:
                return word
    return None


def _avoid_hit(term, item_id, entry):
    """参数单里的忌口词碰到这味料没有：id、中文名、味，三种。"""
    if not isinstance(term, str):
        return False
    if term == item_id or term == entry.get("name"):
        return True
    return term in (entry.get("flavor") or [])


def _check_item(item, label, bencao, is_dish, people):
    """一道菜或一壶茶：名字、料、量、法；菜还有 kind，两样都有 sources。"""
    if not isinstance(item, dict):
        return "{}不是对象".format(label)
    name = item.get("name")
    if not isinstance(name, str) or not name.strip():
        return "{}缺 name".format(label)
    if is_dish:
        kind = item.get("kind")
        if kind not in DISH_KINDS:
            return "{}的 kind“{}”不在允许的范围里（{}）".format(
                label, kind, "、".join(DISH_KINDS)
            )
    method = item.get("method")
    if method not in METHODS:
        return "{}的 method“{}”不在允许的做法里".format(label, method)
    ingredients = item.get("ingredients")
    if not isinstance(ingredients, list) or not ingredients:
        return "{}没有料".format(label)
    for ingredient in ingredients:
        if not isinstance(ingredient, dict):
            return "{}的料不是对象".format(label)
        item_id = ingredient.get("item")
        entry = bencao.get(item_id)
        if entry is None:
            return "{}的料“{}”不在本草库里".format(label, item_id)
        if entry.get("kind") not in BASIC_KINDS:
            return "{}的料“{}”是{}，厨神不开方子".format(
                label, item_id, entry.get("kind")
            )
        qty = ingredient.get("qty")
        if not _is_number(qty) or qty <= 0:
            return "{}的料“{}”量不对".format(label, item_id)
        unit = ingredient.get("unit")
        if not isinstance(unit, str) or not unit.strip():
            return "{}的料“{}”没有单位".format(label, item_id)
        for person in people:
            tag = person.get("tag", "某人")
            for term in person.get("avoid") or []:
                if _avoid_hit(term, item_id, entry):
                    return "{}的料“{}”碰到 {} 的忌口“{}”".format(
                        label, item_id, tag, term
                    )
    sources = item.get("sources")
    if not isinstance(sources, list):
        return "{}没有 sources".format(label)
    for source in sources:
        if not isinstance(source, str) or source not in bencao:
            return "{}的 sources 里“{}”不在本草库里".format(label, source)
    return None


def _check_plan(plan, canshu, bencao, banned):
    """检查一个方案。合格返回 None，不合格返回理由。"""
    if not isinstance(plan, dict):
        return "方案不是对象"
    plan_id = plan.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id.strip():
        return "方案缺 plan_id"
    prefix = "方案 {}：".format(plan_id)

    days = plan.get("days")
    if not isinstance(days, list):
        return prefix + "days 不是数组"
    wanted_days = canshu["range"]["days"]
    if len(days) != wanted_days:
        return prefix + "天数对不上（参数单要 {} 天，给了 {} 天）".format(
            wanted_days, len(days)
        )

    wanted_meals = canshu["range"]["meals"]
    for index, day in enumerate(days, start=1):
        if not isinstance(day, dict):
            return prefix + "第 {} 天不是对象".format(index)
        if day.get("day") != index:
            return prefix + "第 {} 天的 day 写成了 {}".format(index, day.get("day"))
        meals = day.get("meals")
        if not isinstance(meals, list):
            return prefix + "第 {} 天的 meals 不是数组".format(index)
        labels = [
            meal.get("meal") if isinstance(meal, dict) else None for meal in meals
        ]
        if sorted(labels) != sorted(wanted_meals):
            return prefix + "第 {} 天的餐和参数单对不上".format(index)
        for meal in meals:
            dishes = meal.get("dishes")
            if not isinstance(dishes, list) or not dishes:
                return prefix + "第 {} 天 {} 没有菜".format(index, meal.get("meal"))
            for dish in dishes:
                reason = _check_item(
                    dish, "菜", bencao, True, canshu.get("people") or []
                )
                if reason:
                    return prefix + "第 {} 天 {}".format(index, reason)
        if canshu["range"]["drinks"]:
            drinks = day.get("drinks")
            if not isinstance(drinks, list) or not drinks:
                return prefix + "第 {} 天没有饮".format(index)
            for drink in drinks:
                reason = _check_item(
                    drink, "饮", bencao, False, canshu.get("people") or []
                )
                if reason:
                    return prefix + "第 {} 天 {}".format(index, reason)

    banned_word = _find_banned(plan, banned)
    if banned_word:
        return prefix + "文字里有禁词“{}”".format(banned_word)
    return None


def ask(chef, canshu: dict, llm, timeout: float = TIMEOUT):
    """把参数单交给厨神，拿回合格的方案和被丢掉的方案。

    厨神只拿到参数单的深拷贝和 llm；本人库、天时单、主人的设置一样都不给。
    """
    if not isinstance(chef, 厨神):
        raise TypeError("先 load 一个厨神，再 ask")
    if not isinstance(canshu, dict):
        raise ValueError("参数单要是 JSON 对象")
    # 每次调用也再查一遍说明书
    _check_skill(chef.skill, chef.path)

    canshu_copy = copy.deepcopy(canshu)
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(chef.teach, canshu_copy, llm)
    try:
        result = future.result(timeout=timeout)
    except FutureTimeout:
        executor.shutdown(wait=False, cancel_futures=True)
        return [], [(None, "厨神超过 {:g} 秒没回来".format(timeout))]
    except Exception as exc:  # 厨神崩了，不让食神跟着崩
        executor.shutdown(wait=False, cancel_futures=True)
        return [], [(None, "厨神抛异常：{}".format(exc))]
    else:
        executor.shutdown(wait=False)

    if not isinstance(result, dict):
        return [], [(result, "厨神回来的不是 JSON 对象")]
    if result.get("request_id") != canshu.get("request_id"):
        return [], [(result, "方案的 request_id 和参数单对不上")]
    plans = result.get("plans")
    if not isinstance(plans, list):
        return [], [(result, "方案里的 plans 不是数组")]
    if not 2 <= len(plans) <= 3:
        return [], [
            (result, "方案要是两三个，这次给了 {} 个".format(len(plans)))
        ]

    if result.get("teacher") != chef.name:
        return [], [
            (
                result,
                "方案的 teacher“{}”和说明书的 name“{}”对不上".format(
                    result.get("teacher"), chef.name
                ),
            )
        ]

    seen_plan_ids = set()
    for plan in plans:
        if isinstance(plan, dict) and isinstance(plan.get("plan_id"), str):
            if plan["plan_id"] in seen_plan_ids:
                return [], [
                    (result, "一次回复里 plan_id 重复了：{}".format(plan["plan_id"]))
                ]
            seen_plan_ids.add(plan["plan_id"])

    bencao = _bencao()
    banned = _banned_words()
    passed = []
    dropped = []
    for plan in plans:
        reason = _check_plan(plan, canshu, bencao, banned)
        if reason:
            dropped.append((plan, reason))
        else:
            passed.append(plan)
    return passed, dropped
