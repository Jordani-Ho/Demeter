#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""食神：一条命令跟食神说话，一条命令出本周的食谱、饮谱和采买清单。

    python 食神/食神.py 记 "我爸和我都是阴虚火旺，没什么忌口，我们住在圣荷西"
    python 食神/食神.py 本周 [--买 日|周|月]

“本周”从头走到尾：本人库 + 天时 → 抽参 → 插口问厨神甲 → 定夺 → 采买，
把决定写进本人库的 history，生成一份主人好读的 Markdown（`我的食神/本周.md`），
同时打印出来。没定成的，只说一句“这周没定成”和原因，不报错退出。

对外两个维护用的函数（测试用得到）：

    ji_command(text, llm) -> 回给主人的一句话
    week(llm, period="周", tianshi_dan=None) -> (markdown 或 None, 决定或 None, 原因)
"""

import argparse
import os
import sys
import tempfile
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

try:  # 作为包导入时（测试里）
    from . import 定夺, 抽参, 本人库, 天时, 插口, 采买, 记
    from .记 import http_llm
except ImportError:  # 直接跑 python 食神/食神.py 时
    import 定夺
    import 抽参
    import 本人库
    import 天时
    import 插口
    import 采买
    import 记
    from 记 import http_llm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHEF_DIR = os.path.join(ROOT, "厨神甲")
WEEK_FILE = "本周.md"
WEEK_DAYS = 7
WEEKDAYS = "一二三四五六日"
PERIODS = 采买.PERIODS


def ji_command(text, llm):
    """“记”这条命令：一句话进本人库，回一句话。"""
    data = 本人库.load()
    data, message = 记.ji(text, data, llm)
    本人库.save(data)
    return message


def _today_input(data):
    """拿本人库里的地方算天时单；没有地方就算不了。"""
    place = data.get("place") or {}
    for key in ("lat", "lon", "tz"):
        if place.get(key) in (None, ""):
            raise ValueError("还不知道住在哪里，先跟食神说一句住在哪")
    tz_name = place["tz"]
    try:
        now = datetime.now(ZoneInfo(tz_name))
    except (KeyError, ValueError):
        raise ValueError("本人库里的时区不对：{}".format(tz_name))
    return 天时.tianshi(place["lat"], place["lon"], tz_name, now)


def _num(value):
    """数量：整数就写整数，小数留一位。"""
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return round(value, 1)


def _amounts(ingredients):
    """一味一味的“名字 量 单位”，用顿号连起来。"""
    parts = []
    for item in ingredients or []:
        name = item.get("name") or item.get("item")
        parts.append("{} {} {}".format(name, _num(item.get("qty")), item.get("unit")))
    return "、".join(parts)


def _dish_line(dish):
    kind = dish.get("kind")
    head = "{}{}".format(dish.get("name"), "（{}）".format(kind) if kind else "")
    return "- {}：{}。做法：{}".format(
        head, _amounts(dish.get("ingredients")), dish.get("steps", "")
    )


def _drink_line(drink):
    return "- {}：{}。{}，{}。".format(
        drink.get("name"),
        _amounts(drink.get("ingredients")),
        drink.get("method", ""),
        drink.get("when", ""),
    )


def _day_title(tianshi_dan, day_number):
    """“### 第 1 天 · 10 月 19 日（周一）”；日期算不出来就只写第几天。"""
    raw = (tianshi_dan or {}).get("date")
    try:
        first = date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return "### 第 {} 天".format(day_number)
    one = first + timedelta(days=day_number - 1)
    weekday = "周" + WEEKDAYS[one.weekday()]
    return "### 第 {} 天 · {} 月 {} 日（{}）".format(
        day_number, one.month, one.day, weekday
    )


def _caimai_block(name, one):
    """一张采买清单：要买的、家里已经有的。"""
    lines = []
    items = one.get("items") or []
    if items:
        lines.append("**要买**")
        for item in items:
            where = item.get("for") or []
            label = ""
            if where and where != ["四周"]:
                label = "（{}）".format("、".join(where))
            lines.append(
                "- {} {} {}{}".format(
                    item.get("name"),
                    _num(item.get("qty")),
                    item.get("unit"),
                    label,
                )
            )
    else:
        lines.append("要买：没有，家里都够。")

    already = one.get("already_have") or []
    if already:
        lines.append("")
        lines.append("**家里已经有了**")
        for item in already:
            lines.append(
                "- {} {} {}".format(
                    item.get("name"), _num(item.get("qty")), item.get("unit")
                )
            )
    return lines


def render_markdown(decision, caimai, tianshi_dan, period):
    """决定 + 采买清单 -> 主人好读的 Markdown；不出现机器用的字段。"""
    plan = decision.get("plan") or {}
    lines = ["# 本周吃什么", ""]

    idea = (plan.get("idea") or "").strip()
    if idea:
        lines.append("这周按这个思路吃：{}".format(idea))
    reason = (decision.get("reason") or "").strip()
    if reason:
        lines.append("为什么定这个：{}".format(reason))
    lines.append("")

    for day in plan.get("days") or []:
        lines.append(_day_title(tianshi_dan, day.get("day", 0)))
        lines.append("")
        for meal in day.get("meals") or []:
            lines.append("**{}**".format(meal.get("meal")))
            for dish in meal.get("dishes") or []:
                lines.append(_dish_line(dish))
            lines.append("")
        if day.get("drinks"):
            lines.append("**饮**")
            for drink in day["drinks"]:
                lines.append(_drink_line(drink))
            lines.append("")

    lines.append("## 采买清单（按{}）".format(period))
    lines.append("")
    if period == "日":
        for index, one in enumerate(caimai, start=1):
            lines.append("### 第 {} 天".format(index))
            lines.append("")
            lines.extend(_caimai_block("日", one))
            lines.append("")
    else:
        lines.extend(_caimai_block(period, caimai))
        lines.append("")
    return "\n".join(lines)


def save_week(markdown):
    """写到 我的食神/本周.md；先写临时文件再改名。返回路径。"""
    directory = 本人库.home()
    os.makedirs(directory, exist_ok=True)
    file_path = os.path.join(directory, WEEK_FILE)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".本周-", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(markdown)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, file_path)
    except BaseException:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise
    return file_path


def week(llm, period="周", tianshi_dan=None):
    """走完整条：本人库 + 天时 → 抽参 → 插口 → 定夺 → 采买。

    返回 (markdown 或 None, 决定 或 None, 没定成的原因 或 None)。
    """
    if period not in PERIODS:
        raise ValueError("period 只能是 日、周、月，现在是：{}".format(period))

    data = 本人库.load()
    if not data.get("people"):
        raise ValueError("本人库里还没有人，先跟食神说一句家里有谁")
    if tianshi_dan is None:
        tianshi_dan = _today_input(data)

    canshu = 抽参.chouchan(data, tianshi_dan, days=WEEK_DAYS)
    chef = 插口.load(CHEF_DIR)
    passed, dropped = 插口.ask(chef, canshu, llm)
    if not passed:
        reason = dropped[0][1] if dropped else "厨神没有交回方案"
        return None, None, "这周没定成：{}".format(reason)

    today = date.fromisoformat(str(tianshi_dan.get("date")))
    decision, reason = 定夺.dingduo(passed, data, today, llm=llm)
    if decision is None:
        return None, None, reason or "这周没定成。"

    data.setdefault("history", []).append(定夺.history_entry(decision, today))
    本人库.save(data)

    caimai = 采买.caimai(decision, data, period=period)
    markdown = render_markdown(decision, caimai, tianshi_dan, period)
    save_week(markdown)
    return markdown, decision, None


def main(argv=None, llm=None):
    parser = argparse.ArgumentParser(
        prog="食神", description="跟食神说话，或者出本周的食谱、饮谱和采买清单"
    )
    sub = parser.add_subparsers(dest="command")

    talk = sub.add_parser("记", help="跟食神说一句话")
    talk.add_argument("text", help="主人说的话")

    week_parser = sub.add_parser("本周", help="出本周的食谱、饮谱和采买清单")
    week_parser.add_argument(
        "--买", dest="period", default="周", choices=PERIODS, help="采买按日、周还是月"
    )

    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.command is None:
        parser.print_help()
        return 2

    llm = llm or http_llm
    try:
        if args.command == "记":
            print(ji_command(args.text, llm))
            return 0

        markdown, _decision, reason = week(llm, period=args.period)
        if markdown is None:
            print(reason)
            return 0
        print(markdown)
        print("\n（已存到 {}）".format(os.path.join(本人库.home(), WEEK_FILE)))
        return 0
    except RuntimeError as exc:
        print("没做成：{}".format(exc), file=sys.stderr)
        return 1
    except ValueError as exc:
        print("没做成：{}".format(exc), file=sys.stderr)
        return 1
    except (OSError, KeyError) as exc:
        print("没做成：大模型那边出问题了：{}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
