#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""厨神甲的测试。用假的 llm，不连网。运行：

    python -m unittest 测试/测厨神甲.py

设了 SHISHEN_LLM_KEY（或 我的食神/设置.env）时，最后一条连网测试会真跑三次。

这一版厨神甲：大模型只出菜池，代码排一周（开发总纲第五节之三）。
"""

import copy
import importlib.util
import json
import os
import sys
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from 食神 import 插口  # noqa: E402

CHEF_DIR = os.path.join(ROOT, "厨神甲")

CANSHU = {
    "request_id": "req-厨神甲-1",
    "range": {"days": 7, "meals": ["午", "晚"], "drinks": True},
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

STAPLE_KINDS = ("主食", "粥")


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


def dish(name, kind, ids, method, meals, steps="一句做法。"):
    return {
        "name": name,
        "kind": kind,
        "ingredients": list(ids),
        "method": method,
        "steps": steps,
        "why": "养阴润燥，清淡软烂。",
        "meals": list(meals),
    }


def drink(name, ids, method="泡"):
    return {
        "name": name,
        "ingredients": list(ids),
        "method": method,
        "when": "午后",
        "why": "润燥生津。",
    }


def pool_obj():
    """一池合格的菜：汤 5、菜 8、主食 2、饮 5（都是这一家人能吃的料）。"""
    dishes = [
        dish("玉竹瘦肉汤", "汤", ["yuzhu", "zhushourou"], "煲", ["晚"]),
        dish("雪梨银耳汤", "汤", ["xueli", "yiner"], "炖", ["晚"]),
        dish("山药鲫鱼汤", "汤", ["shanyao", "jiyu"], "煲", ["晚"]),
        dish("百合莲子汤", "汤", ["baihe", "lianzi"], "煲", ["晚"]),
        dish("冬瓜豆腐汤", "汤", ["donggua", "doufu"], "煮", ["晚"]),
        dish("清炒菜心", "菜", ["caixin"], "炒", ["午", "晚"]),
        dish("蒸南瓜", "菜", ["nangua"], "蒸", ["午", "晚"]),
        dish("凉拌木耳", "菜", ["muer"], "生食", ["午"]),
        dish("清炒胡萝卜", "菜", ["huluobo"], "炒", ["午", "晚"]),
        dish("香菇蒸蛋", "菜", ["xianggu", "jidan"], "蒸", ["午", "晚"]),
        dish("炒莲藕", "菜", ["lianou"], "炒", ["午", "晚"]),
        dish("清炒大白菜", "菜", ["baicai"], "炒", ["午", "晚"]),
        dish("玉米豆腐", "菜", ["yumi", "doufu"], "煮", ["午", "晚"]),
        dish("米饭", "主食", ["dami"], "煮", ["午", "晚"]),
        dish("小米粥", "粥", ["xiaomi"], "煮", ["午", "晚"]),
    ]
    drinks = [
        drink("雪梨蜂蜜饮", ["xueli", "fengmi"]),
        drink("银耳糖水", ["yiner", "bingtang"], "炖"),
        drink("罗汉果饮", ["luohanguo"]),
        drink("百合饮", ["baihe"]),
        drink("雪梨饮", ["xueli"]),
    ]
    return {"idea": "秋燥，滋阴润燥，清淡软烂。", "dishes": dishes, "drinks": drinks}


def pool_text():
    return json.dumps(pool_obj(), ensure_ascii=False)


def load_main_module():
    spec = importlib.util.spec_from_file_location(
        "chushenjia_main", os.path.join(CHEF_DIR, "main.py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def dish_names_of(plan):
    """一周里菜名和饮名，主食不算。返回 {名字: 次数}。"""
    counts = {}
    for day in plan["days"]:
        for meal in day["meals"]:
            for one in meal["dishes"]:
                if one["kind"] in STAPLE_KINDS:
                    continue
                counts[one["name"]] = counts.get(one["name"], 0) + 1
        for one in day.get("drinks") or []:
            counts[one["name"]] = counts.get(one["name"], 0) + 1
    return counts


class TestChushenJia(unittest.TestCase):
    def setUp(self):
        self.chef = 插口.load(CHEF_DIR)

    def test_week_rules(self):
        """三个方案都合格；七天守住第六节的每餐道数、最多两次、相邻汤不同。"""
        fake = FakeLLM(pool_text())

        passed, dropped = 插口.ask(self.chef, CANSHU, fake)

        self.assertEqual(dropped, [])
        self.assertEqual(len(passed), 3)
        self.assertEqual([plan["plan_id"] for plan in passed], ["A", "B", "C"])
        # 每个方案只问一次（菜池一次就合格）
        self.assertEqual(len(fake.prompts), 3)

        for plan in passed:
            self.assertEqual(len(plan["days"]), 7)
            soups = []
            for index, day in enumerate(plan["days"], start=1):
                self.assertEqual(day["day"], index)
                meals = {meal["meal"]: meal["dishes"] for meal in day["meals"]}
                self.assertEqual(sorted(meals), ["午", "晚"])
                lunch = meals["午"]
                self.assertEqual(
                    sum(1 for one in lunch if one["kind"] in STAPLE_KINDS), 1
                )
                self.assertTrue(
                    1 <= sum(1 for one in lunch if one["kind"] == "菜") <= 2
                )
                dinner = meals["晚"]
                self.assertEqual(
                    sum(1 for one in dinner if one["kind"] == "汤"), 1
                )
                self.assertTrue(
                    1 <= sum(1 for one in dinner if one["kind"] == "菜") <= 2
                )
                self.assertEqual(
                    sum(1 for one in dinner if one["kind"] in STAPLE_KINDS), 1
                )
                self.assertEqual(len(day["drinks"]), 1)
                soups.append(
                    next(one["name"] for one in dinner if one["kind"] == "汤")
                )
            for first, second in zip(soups, soups[1:]):
                self.assertNotEqual(first, second, "相邻两天的汤不能一样")
            counts = dish_names_of(plan)
            for name, count in counts.items():
                self.assertLessEqual(count, 2, "“{}”出现了 {} 次".format(name, count))

    def test_same_pool_same_week(self):
        """同样的菜池排两次，结果一模一样（排法不用随机）。"""
        first, _ = 插口.ask(self.chef, CANSHU, FakeLLM(pool_text()))
        second, _ = 插口.ask(self.chef, CANSHU, FakeLLM(pool_text()))

        self.assertEqual(len(first), 3)
        for left, right in zip(first, second):
            self.assertEqual(
                json.dumps(left["days"], ensure_ascii=False),
                json.dumps(right["days"], ensure_ascii=False),
            )

    def test_small_pool_is_not_submitted(self):
        """菜池太小（汤不够）的不交：重来两次还是不过，就一个方案都不交。"""
        pool = pool_obj()
        pool["dishes"] = [
            one
            for one in pool["dishes"]
            if one["kind"] == "菜" or one["kind"] in STAPLE_KINDS
        ] + [dish("玉竹瘦肉汤", "汤", ["yuzhu", "zhushourou"], "煲", ["晚"])]
        fake = FakeLLM(json.dumps(pool, ensure_ascii=False))

        passed, dropped = 插口.ask(self.chef, CANSHU, fake)

        self.assertEqual(passed, [])
        self.assertEqual(len(dropped), 1)
        self.assertIn("两三个", dropped[0][1])
        self.assertEqual(len(fake.prompts), 9)  # 三个方案 × 三次尝试

    def test_pool_not_enough_for_week(self):
        """菜池数量够，但能上晚餐的汤不够轮换七天：排不满，不交。"""
        module = load_main_module()
        bencao = module._load_bencao()
        pool = pool_obj()
        pool["dishes"] = [
            one
            for one in pool["dishes"]
            if one["kind"] != "汤" or one["name"] in ("玉竹瘦肉汤", "百合莲子汤")
        ]
        pool["dishes"].append(
            dish("姜片鱼汤", "汤", ["shengjiang", "jiyu"], "煲", ["晚"])
        )

        days, reason = module._arrange(pool, CANSHU, bencao)

        self.assertIsNone(days)
        self.assertIn("汤", reason)

    def test_dinner_has_no_ginger(self):
        """带生姜的汤和菜，排菜时不会上晚餐。"""
        canshu = copy.deepcopy(CANSHU)
        canshu["people"] = [
            {"tag": "甲", "age_band": "中年", "constitution": [], "taste": [], "avoid": []}
        ]
        pool = pool_obj()
        pool["dishes"].append(
            dish("姜片鲫鱼汤", "汤", ["shengjiang", "jiyu"], "煲", ["晚"])
        )
        pool["dishes"].append(
            dish("炒菜心加姜", "菜", ["caixin", "shengjiang"], "炒", ["午", "晚"])
        )

        passed, dropped = 插口.ask(
            self.chef, canshu, FakeLLM(json.dumps(pool, ensure_ascii=False))
        )

        self.assertEqual(dropped, [])
        self.assertEqual(len(passed), 3)
        for plan in passed:
            for day in plan["days"]:
                for meal in day["meals"]:
                    if meal["meal"] != "晚":
                        continue
                    for one in meal["dishes"]:
                        ids = [ingredient["item"] for ingredient in one["ingredients"]]
                        self.assertNotIn("shengjiang", ids)

    def test_season_first(self):
        """当令的先排：秋天当令的汤排在前面。"""
        module = load_main_module()
        bencao = module._load_bencao()
        pool = pool_obj()
        pool["dishes"].append(
            dish("苹果汤", "汤", ["pingguo"], "煮", ["晚"])  # 苹果不分季节
        )

        days, reason = module._arrange(pool, CANSHU, bencao)

        self.assertIsNone(reason)
        first_soup = next(
            one for one in days[0]["meals"][1]["dishes"] if one["kind"] == "汤"
        )
        seasons = set()
        for ingredient in first_soup["ingredients"]:
            seasons.update(bencao[ingredient["item"]].get("season") or [])
        self.assertIn("秋", seasons)

    def test_amounts(self):
        """量按 usual_qty 中间值 × 人数折算（中年 1 + 高龄 0.7 = 1.7）。"""
        passed, dropped = 插口.ask(self.chef, CANSHU, FakeLLM(pool_text()))

        self.assertEqual(dropped, [])
        soup = next(
            one
            for one in passed[0]["days"][0]["meals"][1]["dishes"]
            if one["kind"] == "汤"
        )
        amounts = {item["item"]: item["qty"] for item in soup["ingredients"]}
        self.assertEqual(amounts["yuzhu"], 20)  # 12.5 × 1.7 = 21.25 → 20
        self.assertEqual(amounts["zhushourou"], 190)  # 112.5 × 1.7 → 190

    def test_max_tokens(self):
        """每次调用大模型都带 max_tokens=6000。"""
        fake = FakeLLM(pool_text())

        插口.ask(self.chef, CANSHU, fake)

        self.assertTrue(fake.max_tokens)
        self.assertEqual(set(fake.max_tokens), {6000})

    def test_avoid_three_kinds(self):
        """avoid 三种写法（id、中文名、味）在菜池自查里都挡。"""
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
                pool = pool_obj()
                pool["dishes"].append(
                    dish("姜丝炒菜心", "菜", ["caixin", "shengjiang"], "炒", ["午"])
                )

                problems = module._pool_problems(pool, canshu, bencao)

                self.assertTrue(
                    any("忌口" in problem for problem in problems), problems
                )

    def test_unsuits_hits_constitution(self):
        """料的 unsuits 碰到参数单里某个人的体质：菜池自查挡下。"""
        module = load_main_module()
        bencao = module._load_bencao()
        pool = pool_obj()
        pool["dishes"].append(dish("茯苓汤", "汤", ["fuling"], "煲", ["晚"]))

        problems = module._pool_problems(pool, CANSHU, bencao)

        self.assertTrue(any("unsuits" in problem for problem in problems), problems)

    def test_dish_name_must_match_ingredients(self):
        """菜名里提到某味料、料里却没有：菜池自查打回。"""
        module = load_main_module()
        bencao = module._load_bencao()
        pool = pool_obj()
        pool["dishes"].append(
            dish("雪梨蒸蛋", "菜", ["yuzhu"], "蒸", ["午", "晚"])
        )

        problems = module._pool_problems(pool, CANSHU, bencao)

        self.assertTrue(
            any("雪梨" in problem and "料里却没有" in problem for problem in problems),
            problems,
        )

    def test_meals_are_required(self):
        """每道菜都要说明适合午还是晚。"""
        module = load_main_module()
        bencao = module._load_bencao()
        pool = pool_obj()
        del pool["dishes"][0]["meals"]

        problems = module._pool_problems(pool, CANSHU, bencao)

        self.assertTrue(any("meals" in problem for problem in problems), problems)

    def test_retry_uses_feedback(self):
        """菜池有问题时，把问题写进提示词重来一次。"""
        good = pool_text()
        bad = pool_obj()
        bad["dishes"] = [one for one in bad["dishes"] if one["kind"] != "汤"]

        def reply(prompt):
            if "上一回的菜池有这些问题" in prompt:
                return good
            return json.dumps(bad, ensure_ascii=False)

        fake = FakeLLM(reply)

        passed, dropped = 插口.ask(self.chef, CANSHU, fake)

        self.assertEqual(dropped, [])
        self.assertEqual(len(passed), 3)
        self.assertEqual(len(fake.prompts), 6)  # 每个方案：先不过，第二次合格
        self.assertTrue(
            any("汤要至少 5 个" in prompt for prompt in fake.prompts)
        )

    @unittest.skipUnless(
        os.environ.get("SHISHEN_LLM_KEY"), "没有设置 SHISHEN_LLM_KEY，跳过连网测试"
    )
    def test_real_llm_three_runs(self):
        """真的连三次模型：样例本人库抽一周参数单，经插口问厨神甲；三次都要至少两个方案。"""
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

        for run in range(1, 4):
            calls = []

            def counting(prompt, max_tokens=None):
                calls.append(prompt)
                return http_llm(prompt, max_tokens=max_tokens)

            started = time.monotonic()
            passed, dropped = 插口.ask(self.chef, canshu, counting)
            elapsed = time.monotonic() - started

            print(
                "第 {} 次真跑：{} 次调用、{:.1f} 秒、交出 {} 个方案".format(
                    run, len(calls), elapsed, len(passed)
                )
            )
            self.assertGreaterEqual(
                len(passed),
                2,
                "第 {} 次被丢掉的方案：{}".format(run, dropped),
            )


if __name__ == "__main__":
    unittest.main()
