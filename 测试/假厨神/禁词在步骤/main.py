# -*- coding: utf-8 -*-
"""禁词在步骤：第一个方案的 steps 里有“疗程”，另外两个合格。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from 方案 import plan, response  # noqa: E402


def teach(canshu, llm):
    bad = plan("A", canshu)
    bad["days"][0]["meals"][0]["dishes"][0]["steps"] = "按疗程服用。"
    return response(canshu, "禁词在步骤", [bad, plan("B", canshu), plan("C", canshu)])
