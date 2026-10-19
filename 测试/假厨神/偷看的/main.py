# -*- coding: utf-8 -*-
"""偷看的厨神：想从拿到的东西里找本人库，证明插口没把本人库传给它。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from 方案 import plan, response  # noqa: E402

FORBIDDEN = {
    "name",
    "birth_year",
    "notes",
    "lat",
    "lon",
    "tz",
    "feelings",
    "saved",
    "pantry",
    "history",
}


def _leaked(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in FORBIDDEN:
                return True
            if _leaked(value):
                return True
    elif isinstance(node, list):
        return any(_leaked(item) for item in node)
    return False


def teach(canshu, llm):
    idea = "参数里没有本人库" if not _leaked(canshu) else "参数里夹带了本人库"
    return response(
        canshu,
        "偷看的",
        [plan(plan_id, canshu, idea=idea) for plan_id in ("A", "B", "C")],
    )
