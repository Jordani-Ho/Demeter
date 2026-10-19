#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定夺：从几个方案里替主人定下一个。

对外两个函数：

    dingduo(plans, data, today, llm=None) -> (决定 或 None, 一句话)
    history_entry(decision, today) -> dict        # 要写进本人库 history 的那一条

照开发总纲第五节筛：先去掉含忌口的；再去掉跟最近三天吃得太重的；剩下的按点赞、
收藏排；还平手，有大模型就交给它，没有就取第一个。不写本人库。
"""

import json
from datetime import date, timedelta
import os
import secrets

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCAO_DIR = os.path.join(ROOT, "本草库")

RECENT_DAYS = 3  # 多少天内算“重复”
HALF = 0.5  # 前三天的菜里，重复超过一半算太多


def _load_bencao():
    entries = {}
    for filename in sorted(os.listdir(BENCAO_DIR)):
        if not filename.endswith(".json") or filename == "词表.json":
            continue
        with open(os.path.join(BENCAO_DIR, filename), encoding="utf-8-sig") as handle:
            entry = json.load(handle)
        if isinstance(entry.get("id"), str):
            entries[entry["id"]] = entry
    return entries


def _avoid_hit(term, item_id, entry):
    """忌口词碰到这味料没有：本草 id、中文名、词表里的味，三种。"""
    if not isinstance(term, str):
        return False
    if term == item_id or term == entry.get("name"):
        return True
    return term in (entry.get("flavor") or [])


def _ingredients(plan):
    """方案里所有料，返回 [(料 id, 第几天, 餐)]。"""
    result = []
    for day in plan.get("days") or []:
        day_number = day.get("day")
        for meal in day.get("meals") or []:
            for dish in meal.get("dishes") or []:
                for ingredient in dish.get("ingredients") or []:
                    result.append(
                        (
                            ingredient.get("item"),
                            day_number,
                            "第{}天{}".format(day_number, meal.get("meal")),
                        )
                    )
        for drink in day.get("drinks") or []:
            for ingredient in drink.get("ingredients") or []:
                result.append(
                    (ingredient.get("item"), day_number, "第{}天饮".format(day_number))
                )
    return result


def _dish_names(plan):
    names = []
    for day in plan.get("days") or []:
        for meal in day.get("meals") or []:
            for dish in meal.get("dishes") or []:
                name = dish.get("name")
                if isinstance(name, str) and name and name not in names:
                    names.append(name)
    return names


def _has_avoid(plan, data, bencao):
    """方案里有没有碰到任何一个人的 avoid。"""
    people = data.get("people") or []
    for item_id, _day, _where in _ingredients(plan):
        entry = bencao.get(item_id)
        if entry is None:
            continue
        for person in people:
            for term in person.get("avoid") or []:
                if _avoid_hit(term, item_id, entry):
                    return True
    return False


def _recent_dishes(data, today):
    """最近三天吃过哪些菜。"""
    names = set()
    for record in data.get("history") or []:
        raw = record.get("date")
        try:
            eaten = date.fromisoformat(str(raw))
        except ValueError:
            continue
        gap = (today - eaten).days
        if 1 <= gap <= RECENT_DAYS:
            names.update(record.get("dishes") or [])
    return names


def _too_repetitive(plan, recent):
    """方案前三天的菜里，一半以上是最近三天吃过的，就算重复太多。"""
    first_three = []
    for day in (plan.get("days") or [])[:3]:
        for meal in day.get("meals") or []:
            for dish in meal.get("dishes") or []:
                name = dish.get("name")
                if isinstance(name, str) and name:
                    first_three.append(name)
    if not first_three:
        return False
    repeated = sum(1 for name in first_three if name in recent)
    return repeated / len(first_three) > HALF


def _liked_names(data):
    liked = set()
    for feeling in data.get("feelings") or []:
        if feeling.get("kind") in ("like", "save"):
            liked.add(feeling.get("item"))
    for record in data.get("saved") or []:
        liked.add(record.get("item"))
    liked.discard(None)
    return liked


def _tie_break(plans, data, llm):
    """还分不出高下：有大模型问它，没有就取第一个。"""
    if llm is None:
        return plans[0], "平手，先定第一套。"
    lines = ["请从下面这几套里挑一套，只回一行：方案字母｜一句理由。"]
    for plan in plans:
        lines.append("- 方案 {}：{}".format(plan.get("plan_id"), plan.get("idea", "")))
    people = data.get("people") or []
    lines.append(
        "这一家人的口味：{}。".format(
            "、".join(
                item
                for person in people
                for item in (person.get("taste") or [])
            )
            or "没说"
        )
    )
    notes = [note.get("text", "") for person in people for note in person.get("notes") or []]
    if notes:
        lines.append("近况：{}。".format("；".join(notes[-3:])))
    reply = llm("\n".join(lines))
    if isinstance(reply, str):
        text = reply.strip()
        for plan in plans:
            plan_id = plan.get("plan_id")
            if isinstance(plan_id, str) and text.startswith(plan_id):
                reason = text[len(plan_id):].lstrip("｜|:： ").strip()
                return plan, reason or "按近况和口味挑的。"
    return plans[0], "平手，先定第一套。"


def dingduo(plans, data, today, llm=None):
    """从 plans 里定一套；定不成返回 (None, 为什么没定成)。"""
    if not isinstance(plans, list) or not plans:
        return None, "这次没定成：一个方案都没有。"
    bencao = _load_bencao()

    remaining = [plan for plan in plans if not _has_avoid(plan, data, bencao)]
    if not remaining:
        return None, "这次没定成：所有方案里都有要忌口的东西。"

    recent = _recent_dishes(data, today)
    filtered = [plan for plan in remaining if not _too_repetitive(plan, recent)]
    if filtered:
        remaining = filtered

    liked = _liked_names(data)
    scored = []
    for index, plan in enumerate(remaining):
        score = sum(1 for name in _dish_names(plan) if name in liked)
        scored.append((score, index, plan))
    scored.sort(key=lambda item: (-item[0], item[1]))

    reason = "平手，先定第一套。"
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        chosen, reason = _tie_break(remaining, data, llm)
    else:
        chosen = scored[0][2]
        if scored[0][0] > 0:
            reason = "主人点过赞、收藏过的菜里，这一套最多（{} 道）。".format(
                scored[0][0]
            )

    decision = {
        "decision_id": secrets.token_hex(8),
        "request_id": None,
        "chosen_plan": chosen.get("plan_id"),
        "teacher": chosen.get("teacher"),
        "plan": chosen,
        "reason": reason,
    }
    return decision, reason


def history_entry(decision, today):
    """要写进本人库 history 的那一条：日期、决定 id、这几天的菜名。"""
    dishes = []
    for name in _dish_names(decision.get("plan") or {}):
        if name not in dishes:
            dishes.append(name)
    return {
        "date": today.isoformat() if isinstance(today, date) else str(today),
        "decision_id": decision.get("decision_id"),
        "dishes": dishes,
    }
