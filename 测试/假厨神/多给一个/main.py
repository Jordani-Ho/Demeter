# -*- coding: utf-8 -*-
"""多给一个：回了四个方案，这次回复整个不要。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from 方案 import plan, response  # noqa: E402


def teach(canshu, llm):
    return response(
        canshu,
        "多给一个",
        [plan(plan_id, canshu) for plan_id in ("A", "B", "C", "D")],
    )
