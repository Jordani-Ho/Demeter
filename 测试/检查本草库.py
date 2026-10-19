#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查本草库条目。

用法：
    python 测试/检查本草库.py              # 检查 本草库/
    python 测试/检查本草库.py 测试/样例     # 检查指定目录，比如故意写坏的样例

只用 Python 3 标准库。词表（本草库/词表.json）是本草库的一部分，检查时一起读。
全部合格时打印“本草库合格：N 条”并退出 0；
有不合格的，逐条打印哪个文件、哪个字段、哪里不对，退出 1。
"""

import json
import os
import re
import sys

# 仓库根目录：本文件在 <根>/测试/ 下
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DIR = os.path.join(ROOT, "本草库")
WORD_LIST_NAME = "词表.json"
DEFAULT_WORD_LIST = os.path.join(DEFAULT_DIR, WORD_LIST_NAME)

KINDS = ("食材", "药食同源", "调料", "茶饮", "方")
METHODS = ("煎", "炒", "焖", "炸", "焗", "蒸", "煮", "煲", "炖", "泡", "生食")

# 必填字段 -> 应有的类型
REQUIRED = {
    "id": str,
    "name": str,
    "kind": str,
    "nature": str,
    "flavor": list,
    "effects": list,
    "methods": list,
    "sources": list,
}

TYPE_NAMES = {
    str: "字符串",
    list: "数组",
    dict: "对象",
    int: "数",
    float: "数",
    bool: "布尔值",
}

USAGE = "用法：python 测试/检查本草库.py [目录]"


def type_name(value):
    if isinstance(value, bool):
        return "布尔值"
    return TYPE_NAMES.get(type(value), type(value).__name__)


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def load_word_list(directory):
    """读词表。被检查的目录里有 词表.json 就用它，没有就用 本草库/词表.json。"""
    path = os.path.join(directory, WORD_LIST_NAME)
    if not os.path.isfile(path):
        path = DEFAULT_WORD_LIST
    try:
        with open(path, encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except OSError as exc:
        return None, ["词表 {} 读不了：{}".format(path, exc)]
    except json.JSONDecodeError as exc:
        return None, [
            "词表 {} 不是合法的 JSON（第 {} 行第 {} 列：{}）".format(
                path, exc.lineno, exc.colno, exc.msg
            )
        ]
    if not isinstance(data, dict):
        return None, ["词表 {} 应为 JSON 对象".format(path)]
    problems = []
    for key in ("体质", "偏向", "性", "味"):
        value = data.get(key)
        if not isinstance(value, list) or not all(
            isinstance(word, str) for word in value
        ):
            problems.append("词表 {}：{} 应为字符串数组".format(path, key))
    if problems:
        return None, problems
    return data, []


def load_entries(directory):
    """读目录下所有 .json 文件。

    返回 (entries, errors)：
      entries 是 [(文件名, 数据)]，数据只包含成功解析的 JSON；
      errors 是读取阶段就发现的问题。
    """
    try:
        names = sorted(
            name
            for name in os.listdir(directory)
            if name.lower().endswith(".json") and name != WORD_LIST_NAME
        )
    except OSError as exc:
        return [], ["目录 {} 打不开：{}".format(directory, exc)]

    if not names:
        return [], ["目录 {} 里没有 .json 文件".format(directory)]

    entries = []
    errors = []
    for name in names:
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8-sig") as handle:
                text = handle.read()
        except OSError as exc:
            errors.append("{}：文件读不了：{}".format(name, exc))
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            errors.append(
                "{}：不是合法的 JSON（第 {} 行第 {} 列：{}）".format(
                    name, exc.lineno, exc.colno, exc.msg
                )
            )
            continue
        entries.append((name, data))
    return entries, errors


def check_entry(filename, data, known_ids, words, entries_by_id):
    """检查一条条目，返回问题列表（每条一句话，以“文件名：字段”开头）。"""
    problems = []
    natures = set(words["性"])
    tastes = set(words["味"])
    suit_words = set(words["体质"]) | set(words["偏向"])

    def bad(field, message):
        problems.append("{}：{} {}".format(filename, field, message))

    if not isinstance(data, dict):
        return ["{}：整个文件应为 JSON 对象，实际是{}".format(filename, type_name(data))]

    # 1. 文件名和 id 一致；id 只能是小写字母和数字
    stem = filename[:-len(".json")]
    if "id" in data and isinstance(data["id"], str):
        if data["id"] != stem:
            bad("id", "与文件名不一致（文件名是“{}”，id 写的是“{}”）".format(stem, data["id"]))
        if not re.fullmatch(r"[a-z0-9]+", data["id"]):
            bad("id", "“{}”只能用小写字母和数字".format(data["id"]))

    # 2. 必填字段都在，类型对
    for field, expected in REQUIRED.items():
        if field not in data:
            bad(field, "缺少必填字段")
            continue
        value = data[field]
        if not isinstance(value, expected):
            bad(field, "类型应为{}，实际是{}".format(TYPE_NAMES[expected], type_name(value)))
            continue
        # sources 的每一项是对象，单独在下面查
        if expected is list and field != "sources":
            for index, item in enumerate(value):
                if not isinstance(item, str):
                    bad(field, "第 {} 项应为字符串，实际是{}".format(index + 1, type_name(item)))
        if expected is str and value.strip() == "":
            bad(field, "不能是空字符串")

    # 3. kind 只能是五种之一
    kind = data.get("kind")
    if isinstance(kind, str) and kind not in KINDS:
        bad("kind", "“{}”不在允许的值里（{}）".format(kind, "、".join(KINDS)))

    # 3.5 nature 在词表的“性”里，flavor 的每一项在“味”里
    nature = data.get("nature")
    if isinstance(nature, str) and nature.strip() and nature not in natures:
        bad("nature", "“{}”不在词表的性里（{}）".format(nature, "、".join(words["性"])))
    flavor = data.get("flavor")
    if isinstance(flavor, list):
        for index, word in enumerate(flavor):
            if isinstance(word, str) and word not in tastes:
                bad(
                    "flavor",
                    "第 {} 项“{}”不在词表的味里（{}）".format(
                        index + 1, word, "、".join(words["味"])
                    ),
                )

    # 4. methods 只能取允许的做法
    methods = data.get("methods")
    if isinstance(methods, list):
        for index, method in enumerate(methods):
            if isinstance(method, str) and method not in METHODS:
                bad(
                    "methods",
                    "第 {} 项“{}”不是允许的做法（{}）".format(
                        index + 1, method, "、".join(METHODS)
                    ),
                )

    # 5. sources 至少一条，每条要有 title 和 where
    sources = data.get("sources")
    if isinstance(sources, list):
        if not sources:
            bad("sources", "至少要有 1 条出处")
        for index, source in enumerate(sources):
            label = "sources 第 {} 项".format(index + 1)
            if not isinstance(source, dict):
                bad(label, "应为对象，实际是{}".format(type_name(source)))
                continue
            for key in ("title", "where"):
                if key not in source:
                    bad(label, "缺少 {}".format(key))
                elif not isinstance(source[key], str) or source[key].strip() == "":
                    bad(label, "{} 必须是非空字符串".format(key))
            if "note" in source and not isinstance(source["note"], str):
                bad(label, "note 应为字符串，实际是{}".format(type_name(source["note"])))

    # 6. suits / unsuits 只能用词表里的体质和偏向
    for field in ("suits", "unsuits"):
        if field not in data:
            continue
        value = data[field]
        if not isinstance(value, list) or not all(
            isinstance(word, str) for word in value
        ):
            bad(field, "应为字符串数组")
            continue
        for index, word in enumerate(value):
            if word not in suit_words:
                bad(
                    field,
                    "第 {} 项“{}”不在词表的体质或偏向里（{}）".format(
                        index + 1,
                        word,
                        "、".join(words["体质"] + words["偏向"]),
                    ),
                )

    # 方：多一个 ingredients，里面的 item 都要能在本草库里找到
    if kind == "方":
        ingredients = data.get("ingredients")
        if not isinstance(ingredients, list):
            bad("ingredients", "kind 为“方”时必须有 ingredients 数组")
        else:
            if not ingredients:
                bad("ingredients", "kind 为“方”时 ingredients 不能为空")
            for index, ingredient in enumerate(ingredients):
                label = "ingredients 第 {} 项".format(index + 1)
                if not isinstance(ingredient, dict):
                    bad(label, "应为对象，实际是{}".format(type_name(ingredient)))
                    continue
                item = ingredient.get("item")
                if not isinstance(item, str) or item.strip() == "":
                    bad(label, "item 必须是非空字符串")
                elif item not in known_ids:
                    bad(label, "item“{}”不是本草库里的条目".format(item))
                if not is_number(ingredient.get("qty")):
                    bad(label, "qty 应为数")
                elif ingredient["qty"] <= 0:
                    bad(label, "qty 应大于 0")
                unit = ingredient.get("unit")
                if not isinstance(unit, str) or unit.strip() == "":
                    bad(label, "unit 必须是非空字符串")

    # 8. usual_qty：单味必填，方不填
    usual_qty = data.get("usual_qty")
    if kind == "方":
        if usual_qty is not None:
            bad("usual_qty", "“方”不填 usual_qty")
    elif not isinstance(usual_qty, dict):
        bad("usual_qty", "单味条目必须有 usual_qty 对象")
    else:
        low = usual_qty.get("min")
        high = usual_qty.get("max")
        if not is_number(low) or low <= 0:
            bad("usual_qty", "min 要是大于 0 的数")
        if not is_number(high) or high <= 0:
            bad("usual_qty", "max 要是大于 0 的数")
        if is_number(low) and is_number(high) and low > high:
            bad("usual_qty", "min 不能大于 max")
        unit = usual_qty.get("unit")
        if not isinstance(unit, str) or not unit.strip():
            bad("usual_qty", "unit 要是非空字符串")
        if usual_qty.get("per") != "人·餐":
            bad("usual_qty", "per 要写“人·餐”")

    # 9. goes_with / clashes_with 里的 id 都要在本草库里
    for field in ("goes_with", "clashes_with"):
        if field not in data:
            continue
        value = data[field]
        if not isinstance(value, list) or not all(
            isinstance(other, str) for other in value
        ):
            bad(field, "应为本草 id 的字符串数组")
            continue
        for other in value:
            if other not in known_ids:
                bad(field, "“{}”不是本草库里的条目".format(other))

    # 10. clashes_with 相忌要两边都写
    clashes = data.get("clashes_with")
    own_id = data.get("id")
    if isinstance(clashes, list) and isinstance(own_id, str):
        for other_id in clashes:
            other = entries_by_id.get(other_id)
            if not isinstance(other, dict):
                continue  # 上面已经报过“不在库里”
            other_clashes = other.get("clashes_with")
            if not isinstance(other_clashes, list) or own_id not in other_clashes:
                bad(
                    "clashes_with",
                    "“{}”的 clashes_with 里没有写回“{}”（相忌要两边都写）".format(
                        other_id, own_id
                    ),
                )

    return problems


def main(argv):
    if len(argv) > 2:
        print(USAGE)
        return 1
    directory = argv[1] if len(argv) == 2 else DEFAULT_DIR

    entries, problems = load_entries(directory)

    # 词表是本草库的一部分，条目里的性、味、suits/unsuits 都靠它对词
    words, word_problems = load_word_list(directory)
    if words is None:
        for line in word_problems:
            print("不合格：" + line)
        return 1
    problems.extend(word_problems)

    # 7. id 不重复（先收集所有出现过的 id）
    id_to_files = {}
    for filename, data in entries:
        if isinstance(data, dict):
            entry_id = data.get("id")
            if isinstance(entry_id, str) and entry_id.strip():
                id_to_files.setdefault(entry_id, []).append(filename)
    for entry_id, files in sorted(id_to_files.items()):
        if len(files) > 1:
            for filename in files:
                others = "、".join(name for name in files if name != filename)
                problems.append(
                    "{}：id “{}”与 {} 重复".format(filename, entry_id, others)
                )

    known_ids = set(id_to_files)
    entries_by_id = {}
    for filename, data in entries:
        if isinstance(data, dict) and isinstance(data.get("id"), str):
            entries_by_id.setdefault(data["id"], data)

    for filename, data in entries:
        problems.extend(check_entry(filename, data, known_ids, words, entries_by_id))

    if problems:
        for line in problems:
            print("不合格：" + line)
        print("共 {} 处问题。".format(len(problems)))
        return 1

    print("本草库合格：{} 条".format(len(entries)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
