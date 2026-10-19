#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""厨神甲：广东煲汤的路子，按参数单出一池菜，代码排一周。

分工（开发总纲第五节之三）：
- 大模型只负责出一道菜池：汤、菜、主食、饮，每样标明适合午还是晚。每个方案调一次，
  输出上限 6000 token。菜池不过自查才打回，最多两次。
- 代码负责排菜：每餐几道照第六节，一周之内一样菜、一样饮最多两次（主食不算），
  相邻两天的汤不一样，晚餐不放生姜，当令的先排。同样的菜池排出来永远一样。

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
RETRIES = 2  # 菜池不过自查，最多再来两次
MAX_TOKENS = 6000  # 每次调用大模型的输出上限

DISH_KINDS = ("汤", "菜", "主食", "粥", "点心")
METHODS = ("煎", "炒", "焖", "炸", "焗", "蒸", "煮", "煲", "炖", "泡", "生食")
BASIC_KINDS = ("食材", "药食同源", "调料", "茶饮")
STAPLES = ("主食", "粥")
MEALS = ("午", "晚")

# 菜池至少这么多（出得多可以多，排菜时轮流用）
MIN_SOUPS = 5
MIN_DISHES = 8
MIN_STAPLES = 2
MIN_DRINKS = 4

# 一周里同一道菜、同一壶饮最多几次
MAX_TIMES = 2

GINGER = "shengjiang"

# 人数折算：按年龄段
FACTORS = {
    "幼儿": 0.5,
    "少年": 0.8,
    "青年": 1.0,
    "中年": 1.0,
    "老年": 0.9,
    "高龄": 0.7,
}


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
    """菜池里的这一道菜或这一壶饮：结构、料在不在库里、碰不碰忌、菜名老不老实。"""
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
        has_steps = isinstance(item.get("steps"), str) and item["steps"].strip()
        if recipe_id is None and not has_steps:
            problems.append(label + "缺 steps")
    else:
        if not isinstance(item.get("when"), str) or not item["when"].strip():
            problems.append(label + "缺 when")
    if not isinstance(item.get("why"), str) or not item["why"].strip():
        problems.append(label + "缺 why")

    if isinstance(name, str) and name:
        missing = _name_missing_ingredient(name, ids, bencao)
        if missing:
            problems.append(
                label + "的菜名里有“{}”，料里却没有".format("、".join(missing))
            )

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


def _name_missing_ingredient(name, ids, bencao):
    """菜名里出现了本草库某味料的名字，料里却没有：返回这些名字。"""
    if not isinstance(name, str) or not name:
        return []
    missing = []
    for item_id, entry in bencao.items():
        if entry.get("kind") == "方":
            continue
        item_name = entry.get("name")
        if not isinstance(item_name, str) or not item_name:
            continue
        if item_name in name and item_id not in ids:
            missing.append(item_name)
    return sorted(set(missing))


def _meals_of(item):
    """这道菜适合哪几餐：["午"]、["晚"] 或 ["午","晚"]。"""
    meals = item.get("meals") if isinstance(item, dict) else None
    if not isinstance(meals, list):
        return []
    return [meal for meal in meals if meal in MEALS]


def _pool_problems(pool, canshu, bencao):
    """菜池自查：只查菜池本身（结构、料、忌、相忌、菜名），不查重复，
    也不查晚餐生姜——生姜在排菜时挡掉。合格返回空列表。"""
    if not isinstance(pool, dict):
        return ["不是 JSON 对象"]
    problems = []
    idea = pool.get("idea")
    if not isinstance(idea, str) or not idea.strip():
        problems.append("缺 idea")

    dishes = pool.get("dishes")
    if not isinstance(dishes, list):
        dishes = []
        problems.append("dishes 要是数组")
    for index, item in enumerate(dishes, start=1):
        problems.extend(
            _item_problems(item, "菜池第 {} 道".format(index), canshu, bencao, True)
        )
        if isinstance(item, dict) and not _meals_of(item):
            problems.append(
                "菜池第 {} 道没说明适合午还是晚（meals）".format(index)
            )

    soups = [d for d in dishes if isinstance(d, dict) and d.get("kind") == "汤"]
    vegetables = [d for d in dishes if isinstance(d, dict) and d.get("kind") == "菜"]
    staples = [d for d in dishes if isinstance(d, dict) and d.get("kind") in STAPLES]
    if len(soups) < MIN_SOUPS:
        problems.append("汤要至少 {} 个，现在 {} 个".format(MIN_SOUPS, len(soups)))
    if len(vegetables) < MIN_DISHES:
        problems.append(
            "菜要至少 {} 个，现在 {} 个".format(MIN_DISHES, len(vegetables))
        )
    if len(staples) < MIN_STAPLES:
        problems.append(
            "主食要至少 {} 个，现在 {} 个".format(MIN_STAPLES, len(staples))
        )

    if canshu["range"]["drinks"]:
        drinks = pool.get("drinks")
        if not isinstance(drinks, list):
            drinks = []
            problems.append("drinks 要是数组")
        for index, drink in enumerate(drinks, start=1):
            problems.extend(
                _item_problems(
                    drink, "菜池第 {} 壶饮".format(index), canshu, bencao, False
                )
            )
        if len(drinks) < MIN_DRINKS:
            problems.append(
                "饮要至少 {} 个，现在 {} 个".format(MIN_DRINKS, len(drinks))
            )
    return problems


def _ordered(items, season, bencao):
    """按当令先后、再按名字排好；同名的只留一个（同名算同一道菜）。"""
    def key(item):
        ids = _expand(item, bencao)[0]
        on_season = bool(season) and any(
            season in (bencao[one].get("season") or []) for one in ids
        )
        return (0 if on_season else 1, str(item.get("name") or ""))

    ordered = []
    seen = set()
    for item in sorted(items, key=key):
        name = item.get("name")
        if name in seen:
            continue
        seen.add(name)
        ordered.append(item)
    return ordered


def _special_picks(items, days, label):
    """汤、饮：轮流排。返回 (清单 或 None, 排不满的原因)。"""
    if len(items) < 2:
        return None, "能用的{}只有 {} 个，至少要 2 个才排得出相邻两天不重".format(
            label, len(items)
        )
    if len(items) * MAX_TIMES < days:
        return None, "{}不够轮换（{} 个，每样最多两次，排不了 {} 天）".format(
            label, len(items), days
        )
    return [items[day % len(items)] for day in range(days)], None


def _vegetable_picks(items, days, bencao, meal_order):
    """菜：午餐、晚餐各一道，共用“每样最多两次”的额度，同一天不重样。

    先排 meal_order 里的第一餐，再排第二餐。返回 ({(第几天, 餐): 菜} 或 None, 原因)。
    """
    budget = {}
    by_day = {}
    cursor = 0
    schedule = {}
    for day in range(days):
        for meal in meal_order:
            chosen = None
            for step in range(len(items)):
                item = items[(cursor + step) % len(items)]
                name = item.get("name")
                if budget.get(name, 0) >= MAX_TIMES:
                    continue
                if name in by_day.setdefault(day, set()):
                    continue
                if meal not in _meals_of(item):
                    continue
                if meal == "晚" and GINGER in _expand(item, bencao)[0]:
                    continue
                chosen = item
                cursor = (cursor + step + 1) % len(items)
                break
            if chosen is None:
                return None, "菜不够排满（第 {} 天{}没有可用的菜）".format(day + 1, meal)
            budget[chosen["name"]] = budget.get(chosen["name"], 0) + 1
            by_day.setdefault(day, set()).add(chosen["name"])
            schedule[(day, meal)] = chosen
    return schedule, None


def _pick_vegetables(items, days, bencao):
    """试着排菜：先午后晚，排不满再先晚后午；都不行就把原因交回去。"""
    reason = None
    for meal_order in (("午", "晚"), ("晚", "午")):
        schedule, reason = _vegetable_picks(items, days, bencao, meal_order)
        if schedule is not None:
            return schedule, None
    return None, reason


def _arrange(pool, canshu, bencao):
    """菜池 -> 排好的一周。返回 (days 或 None, 排不满的原因)。"""
    days = canshu["range"]["days"]
    season = (canshu.get("tianshi") or {}).get("season")
    dishes = [item for item in pool.get("dishes") or [] if isinstance(item, dict)]

    soups = _ordered(
        [item for item in dishes if item.get("kind") == "汤"], season, bencao
    )
    vegetables = _ordered(
        [item for item in dishes if item.get("kind") == "菜"], season, bencao
    )
    staples = _ordered(
        [item for item in dishes if item.get("kind") in STAPLES], season, bencao
    )

    dinner_soups = [
        item
        for item in soups
        if "晚" in _meals_of(item) and GINGER not in _expand(item, bencao)[0]
    ]
    soup_picks, reason = _special_picks(dinner_soups, days, "能上晚餐的汤")
    if soup_picks is None:
        return None, reason

    vegetable_picks, reason = _pick_vegetables(vegetables, days, bencao)
    if vegetable_picks is None:
        return None, reason

    lunch_staples = [item for item in staples if "午" in _meals_of(item)]
    dinner_staples = [item for item in staples if "晚" in _meals_of(item)]
    if not lunch_staples or not dinner_staples:
        return None, "主食要能上午餐和晚餐各至少一个"

    drink_picks = None
    if canshu["range"]["drinks"]:
        drinks = _ordered(
            [item for item in pool.get("drinks") or [] if isinstance(item, dict)],
            season,
            bencao,
        )
        drink_picks, reason = _special_picks(drinks, days, "饮")
        if drink_picks is None:
            return None, reason

    headcount = _headcount(canshu.get("people") or [])
    built_days = []
    for day in range(days):
        lunch = [
            _build_item(lunch_staples[day % len(lunch_staples)], bencao, headcount, True),
            _build_item(vegetable_picks[(day, "午")], bencao, headcount, True),
        ]
        dinner = [
            _build_item(soup_picks[day], bencao, headcount, True),
            _build_item(vegetable_picks[(day, "晚")], bencao, headcount, True),
            _build_item(
                dinner_staples[day % len(dinner_staples)], bencao, headcount, True
            ),
        ]
        built = {
            "day": day + 1,
            "meals": [
                {"meal": "午", "dishes": lunch},
                {"meal": "晚", "dishes": dinner},
            ],
        }
        if drink_picks is not None:
            built["drinks"] = [
                _build_item(drink_picks[day], bencao, headcount, False)
            ]
        built_days.append(built)
    return built_days, None


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
    """把菜池里的这道菜（料 id 或整条方）补上量，拼成方案格式。"""
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
        built["steps"] = item.get("steps") or "按{}的方做".format(
            (bencao.get(recipe_id) or {}).get("name", "本草")
        )
    else:
        built["when"] = item["when"]
    built["why"] = item["why"]
    built["sources"] = [recipe_id] if recipe_id else list(ids)
    return built


def _ask_one(canshu, bencao, llm, index):
    """要一池菜：大模型回，代码自查；不过关就带上问题重来，最多两次。"""
    feedback = None
    for _attempt in range(RETRIES + 1):
        prompt = _build_prompt(canshu, bencao, index, feedback)
        pool = _parse_json(_call_llm(llm, prompt))
        if pool is None:
            feedback = (
                "你上次回的不是合法 JSON 对象。只输出一个 JSON 对象，"
                "不要别的话、不要代码块。"
            )
            continue

        problems = _pool_problems(pool, canshu, bencao)
        if problems:
            feedback = (
                "上一回的菜池有这些问题，必须真的改动：\n- "
                + "\n- ".join(problems)
                + "\n请输出改正后的完整菜池 JSON，不要别的话、不要代码块。"
            )
            continue

        days, reason = _arrange(pool, canshu, bencao)
        if days is None:
            feedback = (
                "上一回的菜池排不满：{}。请补足能用的汤、菜、主食和饮，"
                "仍然只输出一个菜池 JSON。".format(reason)
            )
            continue
        return {"idea": pool["idea"], "days": days}
    return None


def teach(canshu, llm):
    """按参数单出三个方案；交得出两个就交两个，连两个都没有就交空列表。

    三个方案同时问，每个方案各要一次菜池，免得加起来超过插口的 60 秒。
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
