# -*- coding: utf-8 -*-
"""重名方案：一次回复里两个方案用了同一个 plan_id。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from 方案 import plan, response  # noqa: E402


def teach(canshu, llm):
    return response(
        canshu,
        "重名方案",
        [plan("A", canshu), plan("A", canshu), plan("B", canshu)],
    )
