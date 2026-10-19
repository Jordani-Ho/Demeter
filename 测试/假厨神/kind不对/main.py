# -*- coding: utf-8 -*-
"""kind 不对的厨神：第二个方案的菜 kind 写成“饮料”。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from 方案 import plan, response  # noqa: E402


def teach(canshu, llm):
    good_one = plan("A", canshu)
    bad = plan("B", canshu)
    bad["days"][0]["meals"][0]["dishes"][0]["kind"] = "饮料"
    good_two = plan("C", canshu)
    return response(canshu, "kind不对", [good_one, bad, good_two])
