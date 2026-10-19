#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""厨神甲的测试。用假的 llm，不连网。运行：

    python -m unittest 测试/测厨神甲.py

设了 SHISHEN_LLM_KEY 时，最后一条连网测试会真的跑一次。
"""

import copy
import importlib.util
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from 食神 import 插口  # noqa: E402

CHEF_DIR = os.path.join(ROOT, "厨神甲")

CANSHU = {
    "request_id": "req-厨神甲-1",
    "range": {"days": 2, "meals": ["午", "晚"], "drinks": True},
    "people": [
        {
            "tag": "甲",
            "age_band": "中年",
            "constitution": ["阴虚", "热"],
            "taste": [],
            "avoid": [],
        },
        {
            "tag": "乙",
            "age_band": "高龄",
            "constitution": ["气虚"],
            "taste": [],
            "avoid": [],
        },
    ],
    "tianshi": {"solar_term": "寒露", "season": "秋", "almanac_ji": []},
    "di": {"climate": {}, "region": "沿海"},
}


class FakeLLM:
    """假的大模型：按顺序回固定内容，记下收到的提示词。"""

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if not self.replies:
            raise RuntimeError("假 llm 没有更多回复了")
        return self.replies.pop(0)


def pick(dish_ingredients=None, drink_ingredients=None):
    """写死的“挑选结果”：一个方案，但只给料的 id，不给量。"""
    dish_ids = dish_ingredients or ["yuzhu", "zhushourou"]
    drink_ids = drink_ingredients or ["xueli", "yiner", "bingtang"]
    days = []
    for day_number in range(1, CANSHU["range"]["days"] + 1):
        meals = []
        for meal in CANSHU["range"]["meals"]:
            meals.append(
                {
                    "meal": meal,
                    "dishes": [
                        {
                            "name": "玉竹瘦肉汤",
                            "kind": "汤",
                            "ingredients": dish_ids,
                            "method": "煲",
                            "steps": "洗净，慢火煲一小时。",
                            "why": "润燥补虚。",
                        }
                    ],
                }
            )
        day = {"day": day_number, "meals": meals}
        if CANSHU["range"]["drinks"]:
            day["drinks"] = [
                {
                    "name": "雪梨银耳糖水",
                    "ingredients": drink_ids,
                    "method": "炖",
                    "when": "午后",
                    "why": "润肺生津。",
                }
            ]
        days.append(day)
    return {"idea": "秋燥，滋阴润燥。", "days": days}


def pick_text(**kwargs):
    return json.dumps(pick(**kwargs), ensure_ascii=False)


def load_main_module():
    spec = importlib.util.spec_from_file_location(
        "chushenjia_main", os.path.join(CHEF_DIR, "main.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestChushenJia(unittest.TestCase):
    def setUp(self):
        self.chef = 插口.load(CHEF_DIR)

    def test_amounts_and_plans(self):
        """三个方案都合格；量按 usual_qty 中间值 × 人数折算算对。"""
        fake = FakeLLM([pick_text()] * 3)

        passed, dropped = 插口.ask(self.chef, CANSHU, fake)

        self.assertEqual(dropped, [])
        self.assertEqual(len(passed), 3)
        self.assertEqual([plan["plan_id"] for plan in passed], ["A", "B", "C"])

        dish = passed[0]["days"][0]["meals"][0]["dishes"][0]
        amounts = {item["item"]: item["qty"] for item in dish["ingredients"]}
        # 中年 1 + 高龄 0.7 = 1.7
        self.assertEqual(amounts["yuzhu"], 20)  # 12.5 × 1.7 = 21.25 → 20
        self.assertEqual(amounts["zhushourou"], 190)  # 112.5 × 1.7 = 191.25 → 190

        drink = passed[0]["days"][0]["drinks"][0]
        drink_amounts = {item["item"]: item["qty"] for item in drink["ingredients"]}
        self.assertEqual(drink_amounts["bingtang"], 13)  # 调料到 1 克：7.5 × 1.7 = 12.75

        self.assertIn("yuzhu", fake.prompts[0])
        self.assertIn("参数单", fake.prompts[0])

    def test_unsuits_triggers_retry(self):
        """碰到 unsuits 的方案会重来一次，第二次合格。"""
        bad = pick_text(dish_ingredients=["shengjiang", "zhushourou"])
        good = pick_text()
        fake = FakeLLM([bad, good, good, good])

        passed, dropped = 插口.ask(self.chef, CANSHU, fake)

        self.assertEqual(dropped, [])
        self.assertEqual(len(passed), 3)
        self.assertEqual(len(fake.prompts), 4)
        self.assertTrue(any("unsuits" in prompt for prompt in fake.prompts[1:]))

    def test_retry_twice_still_bad(self):
        """重试两次还不过，三个方案都不交。"""
        bad = pick_text(dish_ingredients=["shengjiang"])
        fake = FakeLLM([bad] * 9)

        passed, dropped = 插口.ask(self.chef, CANSHU, fake)

        self.assertEqual(passed, [])
        self.assertEqual(len(fake.prompts), 9)  # 三个方案 × 三次
        self.assertEqual(len(dropped), 1)
        self.assertIn("两三个", dropped[0][1])

    def test_self_check_clash_and_avoid(self):
        """自查：相忌、忌口都能查出来。"""
        module = load_main_module()
        bencao = {
            "a": {
                "id": "a",
                "name": "甲料",
                "kind": "食材",
                "flavor": [],
                "suits": [],
                "unsuits": [],
                "clashes_with": ["b"],
            },
            "b": {
                "id": "b",
                "name": "乙料",
                "kind": "食材",
                "flavor": ["辛"],
                "suits": [],
                "unsuits": [],
                "clashes_with": ["a"],
            },
            "c": {
                "id": "c",
                "name": "丙料",
                "kind": "食材",
                "flavor": ["辛"],
                "suits": [],
                "unsuits": [],
                "clashes_with": [],
            },
        }
        plan = pick()
        plan["days"][0]["meals"][0]["dishes"][0]["ingredients"] = ["a", "b"]

        problems = module._plan_problems(plan, CANSHU, bencao)
        self.assertTrue(any("相忌" in problem for problem in problems))

        plan["days"][0]["meals"][0]["dishes"][0]["ingredients"] = ["c"]
        canshu = copy.deepcopy(CANSHU)
        canshu["people"][0]["avoid"] = ["辛"]
        problems = module._plan_problems(plan, canshu, bencao)
        self.assertTrue(any("忌口" in problem for problem in problems))

    @unittest.skipUnless(
        os.environ.get("SHISHEN_LLM_KEY"), "没有设置 SHISHEN_LLM_KEY，跳过连网测试"
    )
    def test_real_llm(self):
        """真的连一次模型：样例本人库抽一周参数单，经插口问厨神甲。"""
        from 食神.记 import http_llm
        from 食神.抽参 import chouchan

        with open(
            os.path.join(ROOT, "测试", "样例本人库.json"), encoding="utf-8"
        ) as handle:
            data = json.load(handle)
        tianshi_dan = {
            "date": "2026-10-18",
            "solar_term": "寒露",
            "season": "秋",
            "almanac": {"ji": []},
        }
        canshu = chouchan(data, tianshi_dan, days=7)

        passed, dropped = 插口.ask(self.chef, canshu, http_llm)

        self.assertGreaterEqual(len(passed), 2, "被丢掉的方案：{}".format(dropped))


if __name__ == "__main__":
    unittest.main()
