# -*- coding: utf-8 -*-
"""假厨神共用的样板：按参数单的 range 拼出整套方案。"""


def dish():
    return {
        "name": "玉竹瘦肉汤",
        "kind": "汤",
        "ingredients": [
            {"item": "yuzhu", "name": "玉竹", "qty": 15, "unit": "g"},
            {"item": "zhushourou", "name": "猪瘦肉", "qty": 300, "unit": "g"},
        ],
        "method": "煲",
        "steps": "洗净，慢火煲一小时。",
        "why": "秋天润燥。",
        "sources": ["yuzhu"],
    }


def drink():
    return {
        "name": "枸杞菊花茶",
        "ingredients": [
            {"item": "gouqizi", "name": "枸杞子", "qty": 10, "unit": "g"},
            {"item": "juhua", "name": "菊花", "qty": 5, "unit": "g"},
        ],
        "method": "泡",
        "when": "午后",
        "why": "清肝明目。",
        "sources": ["gouqizi", "juhua"],
    }


def plan(plan_id, canshu, idea="秋燥，滋阴润燥，少煎炸。"):
    days = []
    for day_number in range(1, canshu["range"]["days"] + 1):
        meals = [
            {"meal": meal, "dishes": [dish()]} for meal in canshu["range"]["meals"]
        ]
        entry = {"day": day_number, "meals": meals}
        if canshu["range"]["drinks"]:
            entry["drinks"] = [drink()]
        days.append(entry)
    return {"plan_id": plan_id, "idea": idea, "days": days}


def response(canshu, teacher, plans):
    return {
        "request_id": canshu["request_id"],
        "teacher": teacher,
        "plans": plans,
    }


def valid_response(canshu, teacher, idea="秋燥，滋阴润燥，少煎炸。"):
    return response(
        canshu, teacher, [plan(plan_id, canshu, idea) for plan_id in ("A", "B", "C")]
    )
