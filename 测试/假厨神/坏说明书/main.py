# -*- coding: utf-8 -*-
"""坏说明书的厨神：说明书里想读本人库，插口不该装它。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from 方案 import valid_response  # noqa: E402


def teach(canshu, llm):
    return valid_response(canshu, "坏说明书")
