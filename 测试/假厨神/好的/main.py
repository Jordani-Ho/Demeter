# -*- coding: utf-8 -*-
"""好的厨神：回三个完全合格的方案，料只用本草库现有的条目。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from 方案 import valid_response  # noqa: E402


def teach(canshu, llm):
    return valid_response(canshu, "好的")
