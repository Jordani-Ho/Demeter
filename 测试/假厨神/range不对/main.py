# -*- coding: utf-8 -*-
"""range 不对的厨神：三个方案分别多一天、少一天的饮、法写成“烤”。"""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from 方案 import valid_response  # noqa: E402


def teach(canshu, llm):
    result = valid_response(canshu, "range不对")
    plans = result["plans"]

    # A：多一天
    plans[0]["days"].append(copy.deepcopy(plans[0]["days"][-1]))
    plans[0]["days"][-1]["day"] = len(plans[0]["days"])

    # B：最后一天没有饮
    plans[1]["days"][-1].pop("drinks", None)

    # C：法写成“烤”
    plans[2]["days"][0]["meals"][0]["dishes"][0]["method"] = "烤"

    return result
