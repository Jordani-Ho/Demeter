#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采买的测试。全用写死的决定和本人库，不连网。运行：

    python -m unittest 测试/测采买.py
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from 食神.采买 import caimai  # noqa: E402


def make_plan():
    """七天：每天午大米 50、晚玉竹 10 + 雪梨 100、饮冰糖 5。"""
    days = []
    for number in range(1, 8):
        days.append(
            {
                "day": number,
                "meals": [
                    {
                        "meal": "午",
                        "dishes": [
                            {
                                "name": "粥{}".format(number),
                                "kind": "粥",
                                "ingredients": [
                                    {"item": "dami", "name": "大米", "qty": 50, "unit": "g"}
                                ],
                            }
                        ],
                    },
                    {
                        "meal": "晚",
                        "dishes": [
                            {
                                "name": "汤{}".format(number),
                                "kind": "汤",
                                "ingredients": [
                                    {"item": "yuzhu", "name": "玉竹", "qty": 10, "unit": "g"},
                                    {"item": "xueli", "name": "雪梨", "qty": 100, "unit": "g"},
                                ],
                            }
                        ],
                    },
                ],
                "drinks": [
                    {
                        "name": "饮{}".format(number),
                        "ingredients": [
                            {"item": "bingtang", "name": "冰糖", "qty": 5, "unit": "g"}
                        ],
                    }
                ],
            }
        )
    return {"plan_id": "A", "idea": "秋燥", "days": days}


DECISION = {"decision_id": "dec-1", "chosen_plan": "A", "plan": make_plan()}


def data_with(pantry=None):
    return {"pantry": pantry or []}


def amounts(items):
    return {entry["item"]: entry["qty"] for entry in items}


class TestCaimai(unittest.TestCase):
    def test_week(self):
        """周：七天的料按 item 加起来，减存货。"""
        data = data_with(
            [
                {"item": "yuzhu", "qty": 20, "unit": "g"},
                {"item": "dami", "qty": 500, "unit": "g"},
            ]
        )

        result = caimai(DECISION, data, "周")

        self.assertEqual(result["period"], "周")
        self.assertEqual(result["decision_id"], "dec-1")
        self.assertEqual(amounts(result["items"])["yuzhu"], 50)  # 70 - 20
        self.assertEqual(amounts(result["items"])["xueli"], 700)
        self.assertEqual(amounts(result["items"])["bingtang"], 35)
        self.assertNotIn("dami", amounts(result["items"]))
        self.assertEqual(amounts(result["already_have"])["dami"], 500)

    def test_week_without_pantry(self):
        """没有存货：全都要买。"""
        result = caimai(DECISION, data_with(), "周")

        self.assertEqual(amounts(result["items"])["yuzhu"], 70)

    def test_day_seven_lists_and_stock_first(self):
        """日：七张清单，存货先扣前面的日子。"""
        data = data_with([{"item": "yuzhu", "qty": 20, "unit": "g"}])

        result = caimai(DECISION, data, "日")

        self.assertEqual(len(result), 7)
        first = amounts(result[0]["items"])
        self.assertNotIn("yuzhu", first)  # 第 1 天用存货
        self.assertEqual(amounts(result[0]["already_have"])["yuzhu"], 10)
        # 第 2 天还剩 10 g，也够
        self.assertNotIn("yuzhu", amounts(result[1]["items"]))
        self.assertEqual(amounts(result[1]["already_have"])["yuzhu"], 10)
        # 第 3 天开始要买
        for day in result[2:]:
            self.assertEqual(amounts(day["items"])["yuzhu"], 10)
        total = sum(
            entry["qty"]
            for day in result
            for entry in day["items"] + day["already_have"]
            if entry["item"] == "yuzhu"
        )
        self.assertEqual(total, 70)

    def test_month(self):
        """月：鲜货按周，干货和调料按四周。"""
        data = data_with(
            [
                {"item": "yuzhu", "qty": 20, "unit": "g"},
                {"item": "dami", "qty": 500, "unit": "g"},
            ]
        )

        result = caimai(DECISION, data, "月")

        items = amounts(result["items"])
        # 雪梨、大米是食材：按周
        self.assertEqual(items["xueli"], 700)
        # 玉竹是药食同源：70 × 4 - 20
        self.assertEqual(items["yuzhu"], 260)
        # 冰糖是调料：35 × 4
        self.assertEqual(items["bingtang"], 140)
        # 大米有 500 存货，够一周，进 already_have
        self.assertNotIn("dami", items)
        self.assertEqual(amounts(result["already_have"])["dami"], 500)

    def test_bad_period(self):
        """period 不对就报错。"""
        with self.assertRaises(ValueError):
            caimai(DECISION, data_with(), "年")

    def test_decision_without_plan(self):
        """决定里没有方案就报错。"""
        with self.assertRaises(ValueError):
            caimai({"decision_id": "x"}, data_with(), "周")


if __name__ == "__main__":
    unittest.main()
