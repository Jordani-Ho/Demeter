#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""厨神甲：广东煲汤的路子，按参数单出一池菜，代码排一周。

分工（开发总纲第五节之三）：
- 大模型只负责出一道菜池：汤、菜、主食、饮，每样标明适合午还是晚。每个方案调一次，
  输出上限 6000 token。菜池不过自查才打回，最多两次。
- 代码负责排菜：每餐几道照第六节；一周之内一样菜、一样饮最多两次（主食不算）；
  相邻两天的汤不一样；晚餐不放生姜；当令的先排；汤只放咸汤（肉、骨、鱼、菜），
  糖水、茶只进饮；晚餐主食优先米饭、不和当天午餐一样；同一味料一周最多出现在
  3 天里（米面和调料不算）。同样的菜池排出来永远一样。

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
FRIED_METHODS = ("煎", "炸", "焗")  # 做法里写到这些，method 就得是同一个法

# 菜池至少这么多（出得多可以多，排菜时轮流用）
MIN_SOUPS = 5
MIN_DISHES = 8
MIN_STAPLES = 2
MIN_DRINKS = 4

# 一周里同一道菜、同一壶饮最多几次
MAX_TIMES = 2
# 一周里同一味料最多出现在几天（米面、调料不算）
MAX_INGREDIENT_DAYS = 3

GINGER = "shengjiang"

# 米面：不算“同一味料最多几天”
GRAIN_IDS = ("dami", "xiaomi", "yanmai", "yumi")
# 这些“食材”不算咸汤的主料（水果、坚果、菌藻、豆子、米面）
NON_SAVORY_IDS = (
    "xueli",
    "pingguo",
    "shizi",
    "hetaoren",
    "yiner",
    "heidou",
    "huangdou",
    "lvdou",
) + GRAIN_IDS

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
    """忌口词碰到这味料没有：本草 id、中文名、别名、词表里的味。"""
    if not isinstance(term, str):
        return False
    if term == item_id or term == entry.get("name"):
        return True
    if term in (entry.get("aliases") or []):
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


def _name_missing_ingredient(name, ids, bencao):
    """菜名里出现了本草库某味料的名字或别名，料里却没有：返回这些名字。"""
    if not isinstance(name, str) or not name:
        return []
    missing = []
    for item_id, entry in bencao.items():
        if entry.get("kind") == "方":
            continue
        words = []
        item_name = entry.get("name")
        if isinstance(item_name, str) and item_name:
            words.append(item_name)
        words.extend(
            alias
            for alias in entry.get("aliases") or []
            if isinstance(alias, str) and alias
        )
        for word in words:
            if word in name and item_id not in ids:
                missing.append(word)
    return sorted(set(missing))


def _method_steps_problems(item, label):
    """做法里写了煎、炸、焗，method 却不是这个法的，打回。"""
    steps = item.get("steps")
    if not isinstance(steps, str) or not steps.strip():
        return []
    mentioned = [method for method in FRIED_METHODS if method in steps]
    if not mentioned:
        return []
    method = item.get("method")
    if method in mentioned:
        return []
    return [
        "{}的做法里写了“{}”，method 却是“{}”，要把 method 改成同一个法".format(
            label, "、".join(mentioned), method
        )
    ]


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
    problems.extend(_method_steps_problems(item, label))
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


def _meals_of(item):
    """这道菜适合哪几餐：["午"]、["晚"] 或 ["午","晚"]。"""
    meals = item.get("meals") if isinstance(item, dict) else None
    if not isinstance(meals, list):
        return []
    return [meal for meal in meals if meal in MEALS]


def _pool_problems(pool, canshu, bencao):
    """菜池自查：只查菜池本身（结构、料、忌、相忌、菜名、做法和法对得上），
    不查重复，也不查晚餐生姜——生姜在排菜时挡掉。合格返回空列表。"""
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


def _is_savory_soup(item, bencao):
    """咸汤：有肉、骨、鱼、蛋、豆腐、菜这类主料；糖水、茶不算。"""
    for one in _expand(item, bencao)[0]:
        entry = bencao.get(one)
        if not isinstance(entry, dict):
            continue
        if entry.get("kind") == "食材" and one not in NON_SAVORY_IDS:
            return True
    return False


def _is_rice(item, bencao):
    """米饭：名字里有“饭”，或者主食且用大米。"""
    name = item.get("name")
    if isinstance(name, str) and "饭" in name:
        return True
    return item.get("kind") == "主食" and "dami" in _expand(item, bencao)[0]


def _synthetic_rice(bencao, lunch):
    """菜池里没有米饭时，代码补一个；拿它当晚餐主食。"""
    if lunch is not None and lunch.get("name") == "米饭":
        if "xiaomi" in bencao and lunch.get("name") != "小米粥":
            return {
                "name": "小米粥",
                "kind": "粥",
                "ingredients": ["xiaomi"],
                "method": "煮",
                "steps": "小米淘洗，加水煮成软烂的粥。",
                "why": "日常主食，平和养胃。",
                "meals": ["晚"],
            }
        return None
    if "dami" not in bencao:
        return None
    return {
        "name": "米饭",
        "kind": "主食",
        "ingredients": ["dami"],
        "method": "煮",
        "steps": "大米淘洗，加水煮成米饭。",
        "why": "日常主食，平和养胃。",
        "meals": ["晚"],
    }


class _Week:
    """排菜时的账本：这道菜用过几次、这味料出现在哪几天。"""

    def __init__(self, bencao):
        self.bencao = bencao
        self.ingredient_days = {}
        self.dish_counts = {}
        self.day_dishes = {}

    def ids(self, item):
        return [one for one in _expand(item, self.bencao)[0] if isinstance(one, str)]

    def exempt(self, item_id):
        """米面、调料不算“同一味料最多几天”。"""
        entry = self.bencao.get(item_id) or {}
        return entry.get("kind") == "调料" or item_id in GRAIN_IDS

    def pressure(self, item):
        """这道菜让几味料多占一天，越小越先排。"""
        total = 0
        for one in self.ids(item):
            if self.exempt(one):
                continue
            total += len(self.ingredient_days.get(one, ()))
        return total

    def dish_count(self, item):
        return self.dish_counts.get(item.get("name"), 0)

    def ingredient_ok(self, item, day):
        for one in self.ids(item):
            if self.exempt(one):
                continue
            if len(self.ingredient_days.get(one, set()) | {day}) > MAX_INGREDIENT_DAYS:
                return False
        return True

    def claim(self, item, day):
        name = item.get("name")
        self.dish_counts[name] = self.dish_counts.get(name, 0) + 1
        self.day_dishes.setdefault(day, set()).add(name)
        for one in self.ids(item):
            if not self.exempt(one):
                self.ingredient_days.setdefault(one, set()).add(day)


def _pick_item(week, items, cursor, day, allowed):
    """从 items 里挑一道：先看允许不允许，再看给几味料加了负担（小的先），同分按次序。

    返回 (挑中的菜 或 None, 新的 cursor)。
    """
    if not items:
        return None, cursor
    candidates = []
    for step in range(len(items)):
        index = (cursor + step) % len(items)
        item = items[index]
        if allowed(item):
            candidates.append((week.pressure(item), step, index, item))
    if not candidates:
        return None, cursor
    _pressure, _step, index, item = min(
        candidates, key=lambda one: (one[0], one[1])
    )
    return item, (index + 1) % len(items)


def _assign(pool, canshu, bencao, meal_order, category_order):
    """按一种排法排一周。排满了返回 (days, None)，排不满返回 (None, 原因)。"""
    days = canshu["range"]["days"]
    season = (canshu.get("tianshi") or {}).get("season")
    week = _Week(bencao)
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
    drinks = (
        _ordered(
            [item for item in pool.get("drinks") or [] if isinstance(item, dict)],
            season,
            bencao,
        )
        if canshu["range"]["drinks"]
        else []
    )

    picked = {
        "soup": {},
        "vegetable": {},
        "lunch_staple": {},
        "dinner_staple": {},
        "drink": {},
    }
    cursors = {"soup": 0, "vegetable": 0, "lunch": 0, "dinner": 0, "drink": 0}

    def pick_soup():
        dinner_soups = [
            item
            for item in soups
            if "晚" in _meals_of(item)
            and GINGER not in _expand(item, bencao)[0]
            and _is_savory_soup(item, bencao)
        ]
        for day in range(1, days + 1):
            def allowed(item, day=day):
                if week.dish_count(item) >= MAX_TIMES:
                    return False
                if day > 1 and item.get("name") == picked["soup"][day - 1].get("name"):
                    return False
                return week.ingredient_ok(item, day)

            item, cursors["soup"] = _pick_item(
                week, dinner_soups, cursors["soup"], day, allowed
            )
            if item is None:
                return (
                    "第 {} 天晚饭的汤排不出来：汤要是咸汤（有肉、骨、鱼或菜），"
                    "晚餐不放生姜，一周同一道汤最多两次，同一味料最多三天"
                ).format(day)
            week.claim(item, day)
            picked["soup"][day] = item
        return None

    def pick_vegetable():
        for day in range(1, days + 1):
            for meal in meal_order:
                def allowed(item, day=day, meal=meal):
                    if week.dish_count(item) >= MAX_TIMES:
                        return False
                    if item.get("name") in week.day_dishes.get(day, set()):
                        return False
                    if meal not in _meals_of(item):
                        return False
                    if meal == "晚" and GINGER in _expand(item, bencao)[0]:
                        return False
                    return week.ingredient_ok(item, day)

                item, cursors["vegetable"] = _pick_item(
                    week, vegetables, cursors["vegetable"], day, allowed
                )
                if item is None:
                    return (
                        "第 {} 天{}的菜排不出来"
                        "（一周同一道菜最多两次，同一味料最多三天）"
                    ).format(day, meal)
                week.claim(item, day)
                picked["vegetable"][(day, meal)] = item
        return None

    def pick_staple():
        lunch_list = [item for item in staples if "午" in _meals_of(item)]
        dinner_list = [item for item in staples if "晚" in _meals_of(item)]
        rice_list = [item for item in dinner_list if _is_rice(item, bencao)]
        for day in range(1, days + 1):
            def lunch_allowed(item, day=day):
                return week.ingredient_ok(item, day)

            lunch, cursors["lunch"] = _pick_item(
                week, lunch_list, cursors["lunch"], day, lunch_allowed
            )
            if lunch is None:
                return "第 {} 天的午餐主食排不出来".format(day)
            week.claim(lunch, day)
            picked["lunch_staple"][day] = lunch

            def dinner_allowed(item, day=day, lunch=lunch):
                if item.get("name") == lunch.get("name"):
                    return False
                return week.ingredient_ok(item, day)

            dinner, cursors["dinner"] = _pick_item(
                week, rice_list, cursors["dinner"], day, dinner_allowed
            )
            if dinner is None and rice_list:
                dinner, cursors["dinner"] = _pick_item(
                    week, dinner_list, cursors["dinner"], day, dinner_allowed
                )
            if dinner is None:
                dinner = _synthetic_rice(bencao, lunch)
                if dinner is None:
                    return (
                        "第 {} 天的晚餐主食排不出来（要米饭，又不能和午餐一样）"
                    ).format(day)
            week.claim(dinner, day)
            picked["dinner_staple"][day] = dinner
        return None

    def pick_drink():
        for day in range(1, days + 1):
            def allowed(item, day=day):
                if week.dish_count(item) >= MAX_TIMES:
                    return False
                return week.ingredient_ok(item, day)

            item, cursors["drink"] = _pick_item(
                week, drinks, cursors["drink"], day, allowed
            )
            if item is None:
                return (
                    "第 {} 天的饮排不出来（一周同一壶饮最多两次，同一味料最多三天）"
                ).format(day)
            week.claim(item, day)
            picked["drink"][day] = item
        return None

    pickers = {
        "汤": pick_soup,
        "菜": pick_vegetable,
        "主食": pick_staple,
        "饮": pick_drink,
    }
    for category in category_order:
        reason = pickers[category]()
        if reason:
            return None, reason

    headcount = _headcount(canshu.get("people") or [])
    built_days = []
    for day in range(1, days + 1):
        lunch = [
            _build_item(picked["lunch_staple"][day], bencao, headcount, True),
            _build_item(picked["vegetable"][(day, "午")], bencao, headcount, True),
        ]
        dinner = [
            _build_item(picked["soup"][day], bencao, headcount, True),
            _build_item(picked["vegetable"][(day, "晚")], bencao, headcount, True),
            _build_item(picked["dinner_staple"][day], bencao, headcount, True),
        ]
        built = {
            "day": day,
            "meals": [
                {"meal": "午", "dishes": lunch},
                {"meal": "晚", "dishes": dinner},
            ],
        }
        if drinks:
            built["drinks"] = [
                _build_item(picked["drink"][day], bencao, headcount, False)
            ]
        built_days.append(built)
    return built_days, None


def _arrange(pool, canshu, bencao):
    """菜池 -> 排好的一周。返回 (days 或 None, 排不满的原因)。

    先午后晚、汤菜主食饮的顺序；排不满就换几种顺序再试（同一个菜池，结果还是一样）。
    """
    attempts = (
        (("午", "晚"), ("汤", "菜", "主食", "饮")),
        (("午", "晚"), ("饮", "汤", "菜", "主食")),
        (("晚", "午"), ("汤", "菜", "主食", "饮")),
        (("午", "晚"), ("菜", "汤", "主食", "饮")),
    )
    first_reason = None
    for meal_order, category_order in attempts:
        days, reason = _assign(pool, canshu, bencao, meal_order, category_order)
        if days is not None:
            return days, None
        if first_reason is None:
            first_reason = reason
    return None, first_reason or "菜池排不满"


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
                "并换着用不同的料（同一味料一周最多出现在三天里），"
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
