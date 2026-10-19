# -*- coding: utf-8 -*-
"""很慢的厨神：睡一会儿再回，用来测超时。"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from 方案 import valid_response  # noqa: E402


def teach(canshu, llm):
    time.sleep(1)
    return valid_response(canshu, "很慢的")
