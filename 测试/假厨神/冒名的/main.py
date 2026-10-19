# -*- coding: utf-8 -*-
"""冒名的厨神：方案里的 teacher 不是说明书的 name。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from 方案 import valid_response  # noqa: E402


def teach(canshu, llm):
    return valid_response(canshu, "别人")
