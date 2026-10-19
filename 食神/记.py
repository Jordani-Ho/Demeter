#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""记：把主人随口说的一句话，变成本人库的改动。

分成两半：大模型只负责把话翻成一串“改动”；改动合不合格、写不写进本人库，由代码管。
大模型碰不到本人库文件。

对外一个函数：

    ji(text, data, llm) -> (新的 data, 回给主人的一句话)

llm 是“一段提示词 -> 一段文字”的函数；测试时换成假的，不连网。

命令行（要设好 SHISHEN_LLM_BASE_URL、SHISHEN_LLM_KEY、SHISHEN_LLM_MODEL）：

    python 食神/记.py "我爸和我都是阴虚火旺，没什么忌口，我们住在圣荷西"
"""

import json
import logging
import os
import sys
import urllib.request

try:  # 作为包导入时（测试里）
    from .本人库 import apply, bencao_names, load, load_word_list, save
    from .设置 import get as read_setting
except ImportError:  # 直接跑 python 食神/记.py 时
    from 本人库 import apply, bencao_names, load, load_word_list, save
    from 设置 import get as read_setting

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROMPT_PATH = os.path.join(ROOT, "食神", "提示词", "记.md")

LOG = logging.getLogger("食神.记")

# 说不清话是说谁的时候，落在主人自己身上
OWNER_NAMES = ("主人", "我", "自己")


def build_prompt(text, data):
    """把提示词模板填好：词表全文、现有的人、这一句原话。"""
    with open(PROMPT_PATH, encoding="utf-8") as handle:
        template = handle.read()
    words = load_word_list()
    word_text = "\n".join(
        "- {}：{}".format(name, "、".join(values)) for name, values in words.items()
    )
    people = data.get("people") or []
    if people:
        people_text = "\n".join(
            "- id：{}，name：{}".format(person.get("id"), person.get("name"))
            for person in people
        )
    else:
        people_text = "（现在还没有人）"
    return (
        template.replace("{{词表}}", word_text)
        .replace("{{现有的人}}", people_text)
        .replace("{{原话}}", text)
    )


def _parse_changes(reply):
    """大模型回来的文字 -> 改动数组；不是合法 JSON 数组就返回 None。"""
    if not isinstance(reply, str):
        return None
    text = reply.strip()
    # 模型常把 JSON 包在 ```json ... ``` 里，先把围栏去掉再试
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        changes = json.loads(text)
    except json.JSONDecodeError:
        return None
    return changes if isinstance(changes, list) else None


def _person_name(data, reference):
    """按 id 或 name 找人，找得到就返回名字。"""
    if not isinstance(reference, str):
        return None
    for person in data.get("people", []):
        if person.get("id") == reference or person.get("name") == reference:
            return person.get("name")
    return None


def _ensure_owner(data):
    """主人还没记进本人库，就先加一条。"""
    for person in data.get("people", []):
        if person.get("name") in OWNER_NAMES:
            return data, person.get("name")
    data, _ = apply(data, [{"op": "add_person", "name": "主人"}])
    return data, "主人"


def _add_original_note(data, text, changes):
    """主人的原话总要留一条 note，挂在这句话说的那个人身上。"""
    targets = []
    for change in changes or []:
        if not isinstance(change, dict):
            continue
        op = change.get("op")
        name = None
        if op == "add_person" and isinstance(change.get("name"), str):
            name = change["name"]
        elif op in ("set", "note"):
            name = _person_name(data, change.get("person"))
        if name and name not in targets and _person_name(data, name):
            targets.append(name)

    if not targets:
        data, name = _ensure_owner(data)
        targets = [name]

    note_changes = [{"op": "note", "person": name, "text": text} for name in targets]
    data, _ = apply(data, note_changes)
    return data


def _make_message(data, applied):
    """回给主人的一句话：只说记下了什么，短的。"""
    ordered = []
    about_person = {}
    other = []
    bencao = bencao_names()

    def put_person(name, description):
        if name not in about_person:
            ordered.append(name)
        about_person[name] = description

    for change in applied:
        op = change.get("op")
        if op == "add_person":
            put_person(change["name"], change["name"])
        elif op == "set":
            name = _person_name(data, change.get("person"))
            if not name:
                continue
            field = change.get("field")
            value = change.get("value")
            if field == "constitution":
                put_person(name, "{}，{}".format(name, "、".join(value)))
            elif field == "taste":
                put_person(name, "{}，口味{}".format(name, "、".join(value)))
            elif field == "avoid":
                if value:
                    put_person(name, "{}，忌口{}".format(name, "、".join(value)))
                else:
                    put_person(name, "{}，没有忌口".format(name))
            elif field == "birth_year":
                put_person(name, "{}，{}年生".format(name, value))
            else:
                put_person(name, "{}，名字改了".format(name))
        elif op == "place":
            place = data.get("place") or {}
            other.append("住在{}".format(place.get("name") or change.get("name")))
        elif op == "pantry":
            other.append(
                "家里有{} {} {}".format(
                    bencao.get(change.get("item"), change.get("item")),
                    change.get("qty"),
                    change.get("unit"),
                )
            )

    parts = [about_person[name] for name in ordered] + other
    if not parts:
        return "记下了。"
    return "记下了：" + "；".join(parts) + "。"


def ji(text, data, llm):
    """把一句话记进本人库。

    text 是主人的原话；data 是现在的本人库；llm 是“提示词 -> 文字”的函数。
    返回 (新的 data, 回给主人的一句话)。被挡下的改动不比给主人听，只写日志。
    """
    reply = llm(build_prompt(text, data))
    changes = _parse_changes(reply)

    if changes is None:
        # 大模型回来的不是合法 JSON：整句当成 note 记下，不报错
        LOG.info("大模型回来的不是 JSON 数组，整句记成 note：%r", reply)
        return _add_original_note(data, text, []), "记下了。"

    new_data, blocked = apply(data, changes)
    blocked_changes = [change for change, _ in blocked]
    applied = [
        change for change in changes if all(change is not item for item in blocked_changes)
    ]
    for change, reason in blocked:
        LOG.info("挡下改动 %s：%s", change, reason)

    new_data = _add_original_note(new_data, text, changes)
    return new_data, _make_message(new_data, applied)


def http_llm(prompt, max_tokens=None):
    """走 OpenAI 兼容的 chat 接口。配置先读环境变量，再读 我的食神/设置.env。"""
    base = read_setting("SHISHEN_LLM_BASE_URL")
    key = read_setting("SHISHEN_LLM_KEY")
    model = read_setting("SHISHEN_LLM_MODEL")
    missing = [
        name
        for name, value in (
            ("SHISHEN_LLM_BASE_URL", base),
            ("SHISHEN_LLM_KEY", key),
            ("SHISHEN_LLM_MODEL", model),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "没有设置：{}（环境变量或 我的食神/设置.env）".format("、".join(missing))
        )

    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }
    if max_tokens:
        body["max_tokens"] = int(max_tokens)

    request = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + key,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        answer = json.load(response)
    return answer["choices"][0]["message"]["content"]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print('用法：python 食神/记.py "一句主人的话"')
        return 2
    try:
        data, message = ji(argv[0], load(), http_llm)
    except RuntimeError as exc:
        print("没记成：{}".format(exc), file=sys.stderr)
        return 1
    except (OSError, KeyError, ValueError) as exc:
        print("没记成：大模型那边出问题了：{}".format(exc), file=sys.stderr)
        return 1
    save(data)
    print(message)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
