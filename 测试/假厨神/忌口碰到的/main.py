# -*- coding: utf-8 -*-
"""忌口碰到的厨神：三个方案的菜里都有生姜，用来测插口的 avoid 检查。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from 方案 import plan, response  # noqa: E402


def teach(canshu, llm):
    plans = [plan(plan_id, canshu) for plan_id in ("A", "B", "C")]
    for one in plans:
        one["days"][0]["meals"][0]["dishes"][0]["ingredients"][0] = {
            "item": "shengjiang",
            "name": "生姜",
            "qty": 5,
            "unit": "g",
        }
    return response(canshu, "忌口碰到的", plans)
