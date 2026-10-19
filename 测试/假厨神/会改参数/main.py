# -*- coding: utf-8 -*-
"""会改参数的厨神：拿到参数单就动手改，插口传的应该是拷贝，原来的不能变。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from 方案 import valid_response  # noqa: E402


def teach(canshu, llm):
    result = valid_response(canshu, "会改参数")
    canshu["range"]["days"] = 99
    canshu["people"] = []
    return result
