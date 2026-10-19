#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采买：把决定算成刚刚好的清单。

对外一个函数：

    caimai(decision, data, period="周") -> 采买清单（“日”返回七张清单的列表）

照开发总纲第五节之二和第三节第 6 小节：
- 周：整周用量按 item 加起来，减存货；
- 日：每天一张，存货先扣前面的日子；
- 月：鲜货（食材）按周买，干货和调料（药食同源、调料）按四周的量一次买；
- 减完小于等于 0 的不列，放进 already_have。
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCAO_DIR = os.path.join(ROOT, "本草库")

PERIODS = ("日", "周", "月")
DRY_KINDS = ("药食同源", "调料")  # 月采买里按四周算的


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


def _num(value):
    """数量：整数就写成整数，小数留一位。"""
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return round(value, 1)


def _add(demand, ingredient, label):
    item = ingredient.get("item")
    unit = ingredient.get("unit")
    qty = ingredient.get("qty")
    if not isinstance(item, str) or not isinstance(unit, str) or not isinstance(qty, (int, float)):
        return
    key = (item, unit)
    entry = demand.setdefault(
        key,
        {
            "item": item,
            "name": ingredient.get("name", item),
            "qty": 0,
            "unit": unit,
            "for": [],
        },
    )
    entry["qty"] += qty
    if label not in entry["for"]:
        entry["for"].append(label)


def _day_demand(day):
    """一天的用量：(item, unit) -> {item, name, qty, unit, for}。"""
    demand = {}
    day_number = day.get("day")
    for meal in day.get("meals") or []:
        for dish in meal.get("dishes") or []:
            for ingredient in dish.get("ingredients") or []:
                _add(
                    demand,
                    ingredient,
                    "第{}天{}".format(day_number, meal.get("meal")),
                )
    for drink in day.get("drinks") or []:
        for ingredient in drink.get("ingredients") or []:
            _add(demand, ingredient, "第{}天饮".format(day_number))
    return demand


def _sum_demand(days):
    """整周用量：把每天的加起来。"""
    demand = {}
    for day in days:
        for entry in _day_demand(day).values():
            key = (entry["item"], entry["unit"])
            target = demand.setdefault(
                key,
                {
                    "item": entry["item"],
                    "name": entry["name"],
                    "qty": 0,
                    "unit": entry["unit"],
                    "for": [],
                },
            )
            target["qty"] += entry["qty"]
            for label in entry["for"]:
                if label not in target["for"]:
                    target["for"].append(label)
    return demand


def _stock(data):
    """存货：(item, unit) -> 数量。"""
    stock = {}
    for entry in data.get("pantry") or []:
        item = entry.get("item")
        unit = entry.get("unit")
        qty = entry.get("qty")
        if isinstance(item, str) and isinstance(unit, str) and isinstance(qty, (int, float)):
            key = (item, unit)
            stock[key] = stock.get(key, 0) + qty
    return stock


def _item(entry, qty, labels=None):
    result = {
        "item": entry["item"],
        "name": entry["name"],
        "qty": _num(qty),
        "unit": entry["unit"],
    }
    if labels is not None:
        result["for"] = list(labels)
    return result


def _deduct(demand, stock):
    """周、月用：把存货从总用量里扣掉。"""
    items = []
    already = []
    for entry in demand.values():
        key = (entry["item"], entry["unit"])
        have = stock.get(key, 0)
        need = entry["qty"] - have
        if need > 0:
            items.append(_item(entry, need, entry["for"]))
        elif have > 0:
            already.append(_item(entry, have))
    return items, already


def _caimai_days(decision, days, stock):
    """日的七张：存货先扣前面的日子。"""
    result = []
    for day in days:
        demand = _day_demand(day)
        items = []
        already = []
        for entry in demand.values():
            key = (entry["item"], entry["unit"])
            have = stock.get(key, 0)
            if have >= entry["qty"]:
                already.append(_item(entry, entry["qty"]))
                stock[key] = have - entry["qty"]
            else:
                items.append(_item(entry, entry["qty"] - have, entry["for"]))
                stock[key] = 0
        result.append(
            {
                "decision_id": decision.get("decision_id"),
                "period": "日",
                "items": items,
                "already_have": already,
            }
        )
    return result


def caimai(decision, data, period="周"):
    """把决定算成采买清单。period 是 日、周、月 之一。"""
    if period not in PERIODS:
        raise ValueError("period 只能是 日、周、月，现在是：{}".format(period))
    plan = decision.get("plan") if isinstance(decision, dict) else None
    if not isinstance(plan, dict) or not isinstance(plan.get("days"), list):
        raise ValueError("决定里没有方案")
    days = plan["days"]
    stock = _stock(data if isinstance(data, dict) else {})

    if period == "日":
        return _caimai_days(decision, days, stock)

    demand = _sum_demand(days)
    if period == "月":
        bencao = _load_bencao()
        monthly = {}
        for key, entry in demand.items():
            kind = (bencao.get(entry["item"]) or {}).get("kind")
            factor = 4 if kind in DRY_KINDS else 1
            monthly[key] = {
                "item": entry["item"],
                "name": entry["name"],
                "qty": entry["qty"] * factor,
                "unit": entry["unit"],
                "for": ["四周"] if factor == 4 else list(entry["for"]),
            }
        demand = monthly

    items, already = _deduct(demand, stock)
    return {
        "decision_id": decision.get("decision_id"),
        "period": period,
        "items": items,
        "already_have": already,
    }
