#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""厨神甲：广东煲汤的路子，按参数单出三个方案。

分工：
- 大模型只负责挑：每天每餐做什么菜、用哪几味料（本草 id 或整条方）、用什么法、一句做法、一句为什么。
  每个方案单独调一次，一共三次，输出上限 6000 token。
- 代码负责算量，拼成开发总纲第三节第 4 小节的方案格式，并且自查、重试。

对外一个函数：

    teach(canshu, llm) -> dict
"""

import inspect
import json
import os
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCAO_DIR = os.path.join(ROOT, "本草库")
PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt.md")

TEACHER = "厨神甲"
PLAN_IDS = ("A", "B", "C")
RETRIES = 2  # 最多重来两次，加上第一次一共三次
MAX_TOKENS = 6000  # 每次调用大模型的输出上限

DISH_KINDS = ("汤", "菜", "主食", "粥", "点心")
METHODS = ("煎", "炒", "焖", "炸", "焗", "蒸", "煮", "煲", "炖", "泡", "生食")
BASIC_KINDS = ("食材", "药食同源", "调料", "茶饮")
STAPLES = ("主食", "粥")

# 人数折算：按年龄段
FACTORS = {
    "幼儿": 0.5,
    "少年": 0.8,
    "青年": 1.0,
    "中年": 1.0,
    "老年": 0.9,
    "高龄": 0.7,
}

GINGER = "shengjiang"


def _load_bencao():
    """读本草库：id -> 条目。词表.json 不是条目。"""
    entries = {}
    for filename in sorted(os.listdir(BENCAO_DIR)):
        if not filename.endswith(".json") or filename == "词表.json":
            continue
        with open(os.path.join(BENCAO_DIR, filename), encoding="utf-8-sig") as handle:
            entry = json.load(handle)
        if isinstance(entry.get("id"), str):
            entries[entry["id"]] = entry
    return entries


def _brief(entry):
    """本草表的一行。"""
    def join(value):
        return "、".join(value) if isinstance(value, list) and value else "—"

    return "{} | {} | {} | {} | {} | {} | {} | {} | {} | {}".format(
        entry.get("id"),
        entry.get("name"),
        entry.get("kind"),
        entry.get("nature"),
        join(entry.get("suits")),
        join(entry.get("unsuits")),
        join(entry.get("methods")),
        join(entry.get("season")),
        join(entry.get("goes_with")),
        join(entry.get("clashes_with")),
    )


def _avoid_hit(term, item_id, entry):
    """忌口词碰到这味料没有：本草 id、中文名、词表里的味，三种。"""
    if not isinstance(term, str):
        return False
    if term == item_id or term == entry.get("name"):
        return True
    return term in (entry.get("flavor") or [])


def _forbidden(canshu, bencao):
    """先算好：这一家人的体质、忌口碰到的料有哪些，给模型一张禁用单。"""
    reasons = {}
    people = canshu.get("people") or []
    for item_id, entry in bencao.items():
        if entry.get("kind") == "方":
            continue
        for person in people:
            tag = person.get("tag", "某人")
            hits = sorted(
                set(entry.get("unsuits") or []) & set(person.get("constitution") or [])
            )
            if hits:
                reasons.setdefault(item_id, set()).add(
                    "{}的体质 {}".format(tag, "、".join(hits))
                )
            for term in person.get("avoid") or []:
                if _avoid_hit(term, item_id, entry):
                    reasons.setdefault(item_id, set()).add(
                        "{}的忌口 {}".format(tag, term)
                    )
    return {item_id: sorted(items) for item_id, items in reasons.items()}


def _bencao_table(canshu, bencao):
    """只列这一家人能用的本草：禁用单里的料直接不出现，免得模型看花眼。"""
    forbidden = _forbidden(canshu, bencao)
    single = [
        entry
        for entry in bencao.values()
        if entry.get("kind") != "方" and entry["id"] not in forbidden
    ]
    recipes = [
        entry
        for entry in bencao.values()
        if entry.get("kind") == "方"
        and all(
            ingredient.get("item") not in forbidden
            for ingredient in entry.get("ingredients") or []
        )
    ]
    lines = [
        "id | 名字 | 种类 | 性 | 适合 | 不适合 | 做法 | 当令 | 相宜 | 相忌",
        "--- | --- | --- | --- | --- | --- | --- | --- | --- | ---",
    ]
    lines += [_brief(entry) for entry in sorted(single, key=lambda e: e["id"])]
    if recipes:
        lines += ["", "### 方（整道汤、茶，可以整个照用）", ""]
        lines += [_brief(entry) for entry in sorted(recipes, key=lambda e: e["id"])]
    return "\n".join(lines)


def _people_note(people):
    """参数单里的人，写成人话：几个人、什么年龄段、什么体质、什么忌口。"""
    bands = {}
    constitutions = set()
    avoids = set()
    for person in people:
        band = person.get("age_band") or "不知道年龄段"
        bands[band] = bands.get(band, 0) + 1
        constitutions.update(person.get("constitution") or [])
        avoids.update(person.get("avoid") or [])
    parts = ["一共 {} 人".format(len(people))]
    parts.append("、".join("{} {}".format(band, count) for band, count in bands.items()))
    if constitutions:
        parts.append("体质：" + "、".join(sorted(constitutions)))
    if avoids:
        parts.append("忌口：" + "、".join(sorted(avoids)))
    return "；".join(parts)


def _forbidden_table(canshu, bencao):
    forbidden = _forbidden(canshu, bencao)
    if not forbidden:
        return "（没有）"
    lines = []
    for item_id in sorted(forbidden):
        lines.append(
            "- {} {}：{}".format(
                item_id, bencao[item_id].get("name"), "；".join(forbidden[item_id])
            )
        )
    return "\n".join(lines)


def _headcount(people):
    return sum(FACTORS.get(person.get("age_band"), 1.0) for person in people)


def _build_prompt(canshu, bencao, index, feedback=None):
    with open(PROMPT_PATH, encoding="utf-8") as handle:
        template = handle.read()
    return (
        template.replace("{{本草表}}", _bencao_table(canshu, bencao))
        .replace("{{不能用的料}}", _forbidden_table(canshu, bencao))
        .replace("{{这一家人}}", _people_note(canshu.get("people") or []))
        .replace("{{人数折算}}", "{:g}".format(_headcount(canshu.get("people") or [])))
        .replace("{{参数单}}", json.dumps(canshu, ensure_ascii=False, indent=2))
        .replace("{{方案序号}}", str(index))
        .replace("{{上回的问题}}", feedback or "（没有）")
    )


def _parse_json(reply):
    """大模型回来的文字 -> JSON 对象；解析不了返回 None。"""
    if not isinstance(reply, str):
        return None
    text = reply.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _call_llm(llm, prompt):
    """调大模型。llm 支持 max_tokens 就传 6000，不支持就只传提示词。"""
    try:
        parameters = inspect.signature(llm).parameters
    except (TypeError, ValueError):
        parameters = {}
    if "max_tokens" in parameters:
        return llm(prompt, max_tokens=MAX_TOKENS)
    return llm(prompt)


def _expand(item, bencao):
    """把一道菜/饮展开成料的 id。

    返回 (料 id 列表, 方 id 或 None, 名字, 法, 问题)。
    用了 recipe（整条方）就按方的配料展开。
    """
    recipe_id = item.get("recipe")
    if recipe_id is not None:
        if not isinstance(recipe_id, str):
            return [], None, None, None, "recipe 要是字符串（方的 id）"
        recipe = bencao.get(recipe_id)
        if recipe is None or recipe.get("kind") != "方":
            return [], None, None, None, "recipe“{}”不是本草库里的方".format(recipe_id)
        ids = [
            ingredient.get("item")
            for ingredient in recipe.get("ingredients") or []
            if isinstance(ingredient, dict)
        ]
        name = item.get("name") or recipe.get("name")
        method = item.get("method") or (recipe.get("methods") or [None])[0]
        return ids, recipe_id, name, method, None

    name = item.get("name")
    method = item.get("method")
    ids = item.get("ingredients")
    if not isinstance(ids, list) or not ids:
        return [], None, name, method, "没有料"
    return ids, None, name, method, None


def _item_problems(item, label, canshu, bencao, is_dish):
    """一道菜或一壶饮：结构、料在不在库里、碰不碰忌。"""
    if not isinstance(item, dict):
        return [label + "不是对象"]
    problems = []

    ids, recipe_id, name, method, expansion_problem = _expand(item, bencao)
    if expansion_problem:
        return [label + "的" + expansion_problem]
    if recipe_id is not None and item.get("ingredients"):
        problems.append(label + "用了 recipe 就别再写 ingredients")
    if not isinstance(name, str) or not name.strip():
        problems.append(label + "缺 name")
    if is_dish:
        if item.get("kind") not in DISH_KINDS:
            problems.append(label + "的 kind 不在允许的范围里")
    if method not in METHODS:
        problems.append(label + "的 method 不在允许的做法里")
    if is_dish:
        if not isinstance(item.get("steps"), str) or not item["steps"].strip():
            problems.append(label + "缺 steps")
    else:
        if not isinstance(item.get("when"), str) or not item["when"].strip():
            problems.append(label + "缺 when")
    if not isinstance(item.get("why"), str) or not item["why"].strip():
        problems.append(label + "缺 why")

    people = canshu.get("people") or []
    clean = []
    for one in ids:
        entry = bencao.get(one) if isinstance(one, str) else None
        if entry is None:
            problems.append(label + "的料“{}”不在本草库里".format(one))
            continue
        if entry.get("kind") not in BASIC_KINDS:
            problems.append(label + "的料“{}”是方，不能当料用".format(one))
            continue
        clean.append(one)
        for person in people:
            tag = person.get("tag", "某人")
            hits = sorted(
                set(entry.get("unsuits") or []) & set(person.get("constitution") or [])
            )
            if hits:
                problems.append(
                    "料 {} 的 unsuits“{}”碰到 {} 的体质".format(
                        one, "、".join(hits), tag
                    )
                )
            for term in person.get("avoid") or []:
                if _avoid_hit(term, one, entry):
                    problems.append(
                        "料 {} 碰到 {} 的忌口“{}”".format(one, tag, term)
                    )

    for left in clean:
        for right in clean:
            if left != right and right in (bencao[left].get("clashes_with") or []):
                problems.append("料 {} 和 {} 相忌，不能同菜".format(left, right))
    return problems


def _meal_problems(label, dishes):
    """午餐、晚餐的搭配：午 = 主食 + 1 到 2 道菜；晚 = 1 个汤 + 1 到 2 道菜。"""
    if not isinstance(dishes, list):
        return [label + "的菜不是数组"]
    kinds = [dish.get("kind") for dish in dishes if isinstance(dish, dict)]
    problems = []
    if label == "午":
        staples = sum(1 for kind in kinds if kind in STAPLES)
        vegetables = sum(1 for kind in kinds if kind == "菜")
        if staples != 1:
            problems.append(
                "{}要 1 道主食（主食或粥），现在是 {} 道".format(label, staples)
            )
        if not 1 <= vegetables <= 2:
            problems.append("{}要 1 到 2 道菜，现在是 {} 道".format(label, vegetables))
        strange = sorted({kind for kind in kinds if kind not in STAPLES + ("菜",)})
        if strange:
            problems.append("{}有不允许的 kind：{}".format(label, "、".join(strange)))
    elif label == "晚":
        soups = sum(1 for kind in kinds if kind == "汤")
        vegetables = sum(1 for kind in kinds if kind == "菜")
        if soups != 1:
            problems.append("{}要 1 个汤，现在是 {} 个".format(label, soups))
        if not 1 <= vegetables <= 2:
            problems.append("{}要 1 到 2 道菜，现在是 {} 道".format(label, vegetables))
        strange = sorted({kind for kind in kinds if kind not in ("汤", "菜")})
        if strange:
            problems.append("{}有不允许的 kind：{}".format(label, "、".join(strange)))
    return problems


def _plan_problems(plan, canshu, bencao):
    """大模型给的这一套方案有哪些问题。合格返回空列表。"""
    if not isinstance(plan, dict):
        return ["不是 JSON 对象"]
    problems = []
    if not isinstance(plan.get("idea"), str) or not plan["idea"].strip():
        problems.append("缺 idea")

    days = plan.get("days")
    wanted_days = canshu["range"]["days"]
    if not isinstance(days, list) or len(days) != wanted_days:
        return problems + ["天数要 {} 天".format(wanted_days)]

    wanted_meals = canshu["range"]["meals"]
    dish_names = []
    for index, day in enumerate(days, start=1):
        if not isinstance(day, dict) or day.get("day") != index:
            problems.append("第 {} 天格式不对".format(index))
            continue
        meals = day.get("meals")
        labels = [meal.get("meal") for meal in meals] if isinstance(meals, list) else []
        if sorted(labels) != sorted(wanted_meals):
            problems.append("第 {} 天的餐和参数单对不上".format(index))
            continue
        for meal in meals:
            label = "第 {} 天 {}".format(index, meal.get("meal"))
            dishes = meal.get("dishes")
            if not isinstance(dishes, list) or not dishes:
                problems.append(label + "没有菜")
                continue
            problems.extend(_meal_problems(meal.get("meal"), dishes))
            for dish in dishes:
                problems.extend(_item_problems(dish, label, canshu, bencao, True))
                if not isinstance(dish, dict):
                    continue
                ids, recipe_id, name, _method, _problem = _expand(dish, bencao)
                if recipe_id:
                    name = name or recipe_id
                if name:
                    dish_names.append(name)
                # 天时：晚餐不用生姜
                if meal.get("meal") == "晚" and GINGER in ids:
                    problems.append(label + "晚餐里不能有生姜")

        if canshu["range"]["drinks"]:
            drinks = day.get("drinks")
            if not isinstance(drinks, list) or len(drinks) != 1:
                problems.append("第 {} 天要 1 壶饮".format(index))
            else:
                for drink in drinks:
                    problems.extend(
                        _item_problems(
                            drink,
                            "第 {} 天的饮".format(index),
                            canshu,
                            bencao,
                            False,
                        )
                    )

    counts = {}
    for name in dish_names:
        counts[name] = counts.get(name, 0) + 1
    for name, count in counts.items():
        if count > 2:
            problems.append("菜“{}”出现了 {} 次，一周内最多两次".format(name, count))
    return problems


def _qty(entry, headcount):
    """每味料的量：usual_qty 中间值 × 人数折算，调料到 1 克，别的到 5 克。"""
    usual = entry.get("usual_qty") or {}
    low = usual.get("min") or 0
    high = usual.get("max") or 0
    step = 1 if entry.get("kind") == "调料" else 5
    raw = (low + high) / 2 * headcount
    if raw <= 0:
        return step
    return max(step, int(raw / step + 0.5) * step)


def _build_item(item, bencao, headcount, is_dish):
    """把大模型挑的菜（料 id 或整条方）补上量，拼成方案格式。"""
    ids, recipe_id, name, method, _problem = _expand(item, bencao)
    built = {"name": name}
    if is_dish:
        built["kind"] = item["kind"]
    built["ingredients"] = [
        {
            "item": one,
            "name": bencao[one]["name"],
            "qty": _qty(bencao[one], headcount),
            "unit": (bencao[one].get("usual_qty") or {}).get("unit", "g"),
        }
        for one in ids
    ]
    built["method"] = method
    if is_dish:
        built["steps"] = item["steps"]
    else:
        built["when"] = item["when"]
    built["why"] = item["why"]
    built["sources"] = [recipe_id] if recipe_id else list(ids)
    return built


def _assemble(plan, canshu, bencao):
    """大模型挑的 + 代码算的量 = 一套合格的方案。"""
    headcount = _headcount(canshu.get("people") or [])
    days = []
    for day in plan["days"]:
        built = {"day": day["day"], "meals": []}
        for meal in day["meals"]:
            built["meals"].append(
                {
                    "meal": meal["meal"],
                    "dishes": [
                        _build_item(dish, bencao, headcount, True)
                        for dish in meal["dishes"]
                    ],
                }
            )
        if canshu["range"]["drinks"]:
            built["drinks"] = [
                _build_item(drink, bencao, headcount, False)
                for drink in day["drinks"]
            ]
        days.append(built)
    return {"idea": plan["idea"], "days": days}


def _ask_one(canshu, bencao, llm, index):
    """要一个方案：大模型回，代码查；不过关就把问题告诉它，最多重来两次。"""
    feedback = None
    for _ in range(RETRIES + 1):
        reply = _call_llm(llm, _build_prompt(canshu, bencao, index, feedback))
        plan = _parse_json(reply)
        if plan is None:
            feedback = "你上次回的不是合法 JSON 对象。只输出一个 JSON 对象，不要别的话、不要代码块。"
            continue
        problems = _plan_problems(plan, canshu, bencao)
        if not problems:
            return _assemble(plan, canshu, bencao)
        feedback = "上一回这套方案有这些问题：\n- " + "\n- ".join(
            problems
        ) + "\n请改好，仍然只输出一个 JSON 对象。"
    return None


def teach(canshu, llm):
    """按参数单出三个方案；交得出两个就交两个，连两个都没有就交空列表。

    三个方案同时问，免得三个串行加起来超过插口的 60 秒。
    """
    bencao = _load_bencao()
    with ThreadPoolExecutor(max_workers=len(PLAN_IDS)) as pool:
        futures = [
            pool.submit(_ask_one, canshu, bencao, llm, index)
            for index in range(1, len(PLAN_IDS) + 1)
        ]
        results = [future.result() for future in futures]

    plans = []
    for plan_id, plan in zip(PLAN_IDS, results):
        if plan is not None:
            plan["plan_id"] = plan_id
            plans.append(plan)
    if len(plans) < 2:
        plans = []
    return {
        "request_id": canshu.get("request_id"),
        "teacher": TEACHER,
        "plans": plans,
    }
