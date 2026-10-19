# -*- coding: utf-8 -*-
"""禁词在料名：禁词只写在料的 name 里，按新规定不查这个字段，三个都该过。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from 方案 import plan, response  # noqa: E402


def teach(canshu, llm):
    plans = [plan(plan_id, canshu) for plan_id in ("A", "B", "C")]
    for one in plans:
        one["days"][0]["meals"][0]["dishes"][0]["ingredients"][0]["name"] = "治疗用玉竹"
    return response(canshu, "禁词在料名", plans)
