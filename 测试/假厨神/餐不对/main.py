# -*- coding: utf-8 -*-
"""餐不对的厨神：第一个方案多了一顿“早”，另外两个合格。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from 方案 import valid_response  # noqa: E402


def teach(canshu, llm):
    result = valid_response(canshu, "餐不对")
    first_day = result["plans"][0]["days"][0]
    first_day["meals"].append(
        {"meal": "早", "dishes": [first_day["meals"][0]["dishes"][0]]}
    )
    return result
