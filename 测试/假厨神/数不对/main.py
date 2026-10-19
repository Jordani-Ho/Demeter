# -*- coding: utf-8 -*-
"""数不对的厨神：只回一个方案。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from 方案 import plan, response  # noqa: E402


def teach(canshu, llm):
    return response(canshu, "数不对", [plan("A", canshu)])
