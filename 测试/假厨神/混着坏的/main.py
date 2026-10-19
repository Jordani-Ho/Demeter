# -*- coding: utf-8 -*-
"""混着坏的厨神：三个方案，一个合格，一个用了本草库没有的料，一个写了“治疗”。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from 方案 import plan, response  # noqa: E402


def teach(canshu, llm):
    good = plan("A", canshu)

    bad_item = plan("B", canshu)
    bad_item["days"][0]["meals"][0]["dishes"][0]["ingredients"][0]["item"] = "buzai"

    bad_text = plan("C", canshu, idea="这是治疗糖尿病的方案。")

    return response(canshu, "混着坏的", [good, bad_item, bad_text])
