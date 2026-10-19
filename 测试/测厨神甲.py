#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""厨神甲的测试。用假的 llm，不连网。运行：

    python -m unittest 测试/测厨神甲.py

设了 SHISHEN_LLM_KEY（或 我的食神/设置.env）时，最后一条连网测试会真的跑一次。
"""

import copy
import importlib.util
import json
import os
import sys
import threading
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
    """假的大模型：固定回一段文字，或者按提示词回；记下提示词和 max_tokens。

    三个方案是同时问的，所以这里要线程安全。
    """

    def __init__(self, reply):
        self.reply = reply
        self.prompts = []
        self.max_tokens = []
        self.lock = threading.Lock()

    def __call__(self, prompt, max_tokens=None):
        with self.lock:
            self.prompts.append(prompt)
            self.max_tokens.append(max_tokens)
        if callable(self.reply):
            return self.reply(prompt)
        return self.reply


def plan_obj(drink_recipe=False, day_count=None):
    """写死的“挑选结果”：午晚加饮，结构照第六节的数。"""
    days = []
    total_days = day_count or CANSHU["range"]["days"]
    for day_number in range(1, total_days + 1):
        morning = {
            "meal": "午",
            "dishes": [
                {
                    "name": "第{}天燕麦粥".format(day_number),
                    "kind": "粥",
                    "ingredients": ["yanmai"],
                    "method": "煮",
                    "steps": "燕麦煮至软烂。",
                    "why": "补气养胃。",
                },
                {
                    "name": "第{}天炒肉片".format(day_number),
                    "kind": "菜",
                    "ingredients": ["zhushourou"],
                    "method": "炒",
                    "steps": "少油炒熟。",
                    "why": "补虚。",
                },
            ],
        }
        evening = {
            "meal": "晚",
            "dishes": [
                {
                    "name": "第{}天玉竹汤".format(day_number),
                    "kind": "汤",
                    "ingredients": ["yuzhu", "zhushourou"],
                    "method": "煲",
                    "steps": "慢火煲一小时。",
                    "why": "润燥。",
                },
                {
                    "name": "第{}天蒸梨".format(day_number),
                    "kind": "菜",
                    "ingredients": ["xueli"],
                    "method": "蒸",
                    "steps": "蒸至软烂。",
                    "why": "润肺。",
                },
                {
                    "name": "第{}天米饭".format(day_number),
                    "kind": "主食",
                    "ingredients": ["dami"],
                    "method": "煮",
                    "steps": "煮成软饭。",
                    "why": "养胃。",
                },
            ],
        }
        day = {"day": day_number, "meals": [morning, evening]}
        if drink_recipe:
            day["drinks"] = [
                {
                    "recipe": "xueliyinertangshui",
                    "method": "炖",
                    "when": "午后",
                    "why": "润燥养阴。",
                }
            ]
        else:
            day["drinks"] = [
                {
                    "name": "第{}天银耳饮".format(day_number),
                    "ingredients": ["yiner", "bingtang"],
                    "method": "炖",
                    "when": "午后",
                    "why": "润燥生津。",
                }
            ]
        days.append(day)
    return {"idea": "秋燥，滋阴润燥，清淡软烂。", "days": days}


def plan_text(drink_recipe=False):
    return json.dumps(plan_obj(drink_recipe), ensure_ascii=False)


def load_main_module():
    spec = importlib.util.spec_from_file_location(
        "chushenjia_main", os.path.join(CHEF_DIR, "main.py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestChushenJia(unittest.TestCase):
    def setUp(self):
        self.chef = 插口.load(CHEF_DIR)

    def test_amounts_and_plans(self):
        """三个方案都合格；量按 usual_qty 中间值 × 人数折算算对。"""
        fake = FakeLLM(plan_text())

        passed, dropped = 插口.ask(self.chef, CANSHU, fake)

        self.assertEqual(dropped, [])
        self.assertEqual(len(passed), 3)
        self.assertEqual([plan["plan_id"] for plan in passed], ["A", "B", "C"])

        soup = passed[0]["days"][0]["meals"][1]["dishes"][0]
        amounts = {item["item"]: item["qty"] for item in soup["ingredients"]}
        # 中年 1 + 高龄 0.7 = 1.7
        self.assertEqual(amounts["yuzhu"], 20)  # 12.5 × 1.7 = 21.25 → 20
        self.assertEqual(amounts["zhushourou"], 190)  # 112.5 × 1.7 = 191.25 → 190

        porridge = passed[0]["days"][0]["meals"][0]["dishes"][0]
        self.assertEqual(porridge["ingredients"][0]["qty"], 70)  # 40 × 1.7 = 68 → 70

        drink = passed[0]["days"][0]["drinks"][0]
        drink_amounts = {item["item"]: item["qty"] for item in drink["ingredients"]}
        self.assertEqual(drink_amounts["bingtang"], 13)  # 调料到 1 克：7.5 × 1.7 = 12.75

        self.assertIn("1.7", fake.prompts[0])
        self.assertIn("shengjiang", fake.prompts[0])  # 禁用单里有生姜

    def test_max_tokens(self):
        """每次调用大模型都带 max_tokens=6000。"""
        fake = FakeLLM(plan_text())

        插口.ask(self.chef, CANSHU, fake)

        self.assertTrue(fake.max_tokens)
        self.assertEqual(set(fake.max_tokens), {6000})

    def test_recipe_expansion(self):
        """照方做的饮：sources 写方 id，料按方展开、按人数算量。"""
        fake = FakeLLM(plan_text(drink_recipe=True))

        passed, dropped = 插口.ask(self.chef, CANSHU, fake)

        self.assertEqual(dropped, [])
        drink = passed[0]["days"][0]["drinks"][0]
        self.assertEqual(drink["name"], "雪梨银耳糖水")
        self.assertEqual(drink["sources"], ["xueliyinertangshui"])
        amounts = {item["item"]: item["qty"] for item in drink["ingredients"]}
        self.assertEqual(amounts["xueli"], 255)  # 150 × 1.7
        self.assertEqual(amounts["yiner"], 15)  # 7.5 × 1.7 → 15

    def test_unsuits_triggers_retry(self):
        """碰到 unsuits 的方案会重来一次，第二次合格。"""
        bad = plan_obj()
        bad["days"][0]["meals"][1]["dishes"][0]["ingredients"] = [
            "shengjiang",
            "zhushourou",
        ]
        good = plan_text()

        def reply(prompt):
            if "上一回这套方案有这些问题" in prompt:
                return good
            return json.dumps(bad, ensure_ascii=False)

        fake = FakeLLM(reply)

        passed, dropped = 插口.ask(self.chef, CANSHU, fake)

        self.assertEqual(dropped, [])
        self.assertEqual(len(passed), 3)
        self.assertEqual(len(fake.prompts), 12)  # 每方案两轮、每轮两份
        self.assertTrue(any("unsuits" in prompt for prompt in fake.prompts))

    def test_retry_exhausted(self):
        """重试用完还不过，三个方案都不交。"""
        bad = plan_obj()
        bad["days"][0]["meals"][1]["dishes"][0]["ingredients"] = ["shengjiang"]
        fake = FakeLLM(json.dumps(bad, ensure_ascii=False))

        passed, dropped = 插口.ask(self.chef, CANSHU, fake)

        self.assertEqual(passed, [])
        self.assertEqual(len(fake.prompts), 18)  # 三个方案 × 六份
        self.assertEqual(len(dropped), 1)
        self.assertIn("两三个", dropped[0][1])

    def test_meal_structure(self):
        """午要主食 + 1 到 2 道菜；晚要 1 个汤 + 1 到 2 道菜 + 主食。"""
        module = load_main_module()
        bencao = module._load_bencao()

        # 晚餐去掉主食 → 不合格
        plan = plan_obj()
        del plan["days"][0]["meals"][1]["dishes"][2]
        problems = module._plan_problems(plan, CANSHU, bencao)
        self.assertTrue(
            any("主食" in problem and "晚" in problem for problem in problems),
            problems,
        )

        # 午餐去掉主食 → 不合格
        plan = plan_obj()
        del plan["days"][0]["meals"][0]["dishes"][0]
        problems = module._plan_problems(plan, CANSHU, bencao)
        self.assertTrue(
            any("主食" in problem and "午" in problem for problem in problems),
            problems,
        )

    def test_dish_name_must_match_ingredients(self):
        """名字里提到某味料、料里却没有：打回。"""
        module = load_main_module()
        bencao = module._load_bencao()

        plan = plan_obj()
        plan["days"][0]["meals"][1]["dishes"][1]["name"] = "雪梨蒸蛋"
        plan["days"][0]["meals"][1]["dishes"][1]["ingredients"] = ["yuzhu"]
        problems = module._plan_problems(plan, CANSHU, bencao)
        self.assertTrue(
            any("雪梨" in problem and "料里却没有" in problem for problem in problems),
            problems,
        )

        plan = plan_obj()
        plan["days"][0]["meals"][1]["dishes"][1]["name"] = "雪梨蒸梨"
        problems = module._plan_problems(plan, CANSHU, bencao)
        self.assertFalse(
            any("料里却没有" in problem for problem in problems), problems
        )

    def test_dinner_ginger_and_repeat(self):
        """自查：晚餐不能有生姜；同一道菜或饮一周最多两次，主食不算。"""
        module = load_main_module()
        bencao = module._load_bencao()
        canshu = copy.deepcopy(CANSHU)
        canshu["people"] = [
            {
                "tag": "甲",
                "age_band": "中年",
                "constitution": [],
                "taste": [],
                "avoid": [],
            }
        ]
        canshu["range"]["days"] = 3

        plan = plan_obj(day_count=3)
        for day in plan["days"]:
            for meal in day["meals"]:
                for dish in meal["dishes"]:
                    if dish["kind"] not in ("主食", "粥"):
                        dish["name"] = "同一道菜"
            for drink in day["drinks"]:
                drink["name"] = "同一道菜"
        plan["days"][0]["meals"][1]["dishes"][0]["ingredients"] = ["shengjiang"]

        problems = module._plan_problems(plan, canshu, bencao)

        self.assertTrue(any("生姜" in problem for problem in problems))
        self.assertTrue(any("两次" in problem for problem in problems))

    def test_avoid_three_kinds(self):
        """avoid 三种写法都挡：本草 id、中文名、词表里的味。"""
        module = load_main_module()
        bencao = module._load_bencao()

        for avoid_term in ("shengjiang", "生姜", "辛"):
            with self.subTest(avoid=avoid_term):
                canshu = copy.deepcopy(CANSHU)
                canshu["people"] = [
                    {
                        "tag": "甲",
                        "age_band": "中年",
                        "constitution": [],
                        "taste": [],
                        "avoid": [avoid_term],
                    }
                ]
                plan = plan_obj()
                plan["days"][0]["meals"][0]["dishes"][1]["ingredients"] = ["shengjiang"]

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
