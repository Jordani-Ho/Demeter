#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""插口的测试。全部用假的厨神，不连网。运行：

    python -m unittest 测试/测插口.py
"""

import copy
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from 食神 import 插口  # noqa: E402

FAKE_DIR = os.path.join(ROOT, "测试", "假厨神")

CANSHU = {
    "request_id": "req-测试-1",
    "range": {"days": 2, "meals": ["午", "晚"], "drinks": True},
    "people": [
        {
            "tag": "甲",
            "age_band": "中年",
            "constitution": ["阴虚"],
            "taste": [],
            "avoid": [],
        }
    ],
    "tianshi": {"solar_term": "寒露", "season": "秋", "almanac_ji": []},
    "di": {"climate": {"humid": "偏潮", "temp": "温和"}, "region": "沿海"},
}


def load_fake(name):
    return 插口.load(os.path.join(FAKE_DIR, name))


class TestChakou(unittest.TestCase):
    def test_good_chef(self):
        """好的厨神：三个方案全合格，参数单没被改动。"""
        before = copy.deepcopy(CANSHU)

        passed, dropped = 插口.ask(load_fake("好的"), CANSHU, None)

        self.assertEqual(len(passed), 3)
        self.assertEqual(dropped, [])
        self.assertEqual(CANSHU, before)
        for plan in passed:
            self.assertIn(plan["plan_id"], ("A", "B", "C"))
            self.assertEqual(len(plan["days"]), CANSHU["range"]["days"])

    def test_bad_skill_json_is_rejected(self):
        """坏说明书：reads 里多了“本人库”，装不上。"""
        with self.assertRaises(ValueError) as caught:
            load_fake("坏说明书")

        message = str(caught.exception)
        self.assertIn("reads", message)
        self.assertIn("本人库", message)

    def test_mixed_plans(self):
        """混着坏的：一个合格，一个料不在本草库，一个写了“治疗”。"""
        passed, dropped = 插口.ask(load_fake("混着坏的"), CANSHU, None)

        self.assertEqual([plan["plan_id"] for plan in passed], ["A"])
        self.assertEqual(len(dropped), 2)
        reasons = "；".join(reason for _, reason in dropped)
        self.assertIn("本草库", reasons)
        self.assertIn("禁词", reasons)

    def test_wrong_plan_count(self):
        """数不对：只回一个方案，全部不要。"""
        passed, dropped = 插口.ask(load_fake("数不对"), CANSHU, None)

        self.assertEqual(passed, [])
        self.assertEqual(len(dropped), 1)
        self.assertIn("两三个", dropped[0][1])

    def test_crashing_chef(self):
        """会崩的：食神不跟着崩。"""
        passed, dropped = 插口.ask(load_fake("会崩的"), CANSHU, None)

        self.assertEqual(passed, [])
        self.assertEqual(len(dropped), 1)
        self.assertIn("抛异常", dropped[0][1])
        self.assertIn("假厨神炸了", dropped[0][1])

    def test_peeking_chef_gets_no_personal_library(self):
        """偷看的：它拿到的参数里没有本人库。"""
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        with open(
            os.path.join(home.name, "本人库.json"), "w", encoding="utf-8"
        ) as handle:
            json.dump(
                {
                    "owner": "主人",
                    "place": {"lat": 1, "lon": 2, "tz": "Asia/Shanghai"},
                    "people": [
                        {"id": "p1", "name": "不该被看到的人", "birth_year": 1990}
                    ],
                },
                handle,
                ensure_ascii=False,
            )

        with mock.patch.dict(os.environ, {"SHISHEN_HOME": home.name}):
            passed, dropped = 插口.ask(load_fake("偷看的"), CANSHU, None)

        self.assertEqual(dropped, [])
        self.assertEqual(len(passed), 3)
        for plan in passed:
            self.assertIn("参数里没有本人库", plan["idea"])

    def test_chef_cannot_change_the_parameter_sheet(self):
        """会改参数：厨神改的是拷贝，传进去的参数单不变。"""
        before = copy.deepcopy(CANSHU)

        passed, dropped = 插口.ask(load_fake("会改参数"), CANSHU, None)

        self.assertEqual(CANSHU, before)
        self.assertEqual(dropped, [])
        self.assertEqual(len(passed), 3)

    def test_timeout(self):
        """很慢的：超时当作一个合格方案都没有。"""
        started = time.monotonic()

        passed, dropped = 插口.ask(load_fake("很慢的"), CANSHU, None, timeout=0.05)

        self.assertLess(time.monotonic() - started, 0.9)
        self.assertEqual(passed, [])
        self.assertEqual(len(dropped), 1)
        self.assertIn("超时" if "超时" in dropped[0][1] else "没回来", dropped[0][1])

    def test_not_a_json_object(self):
        """回文字：回来的不是 JSON 对象。"""
        passed, dropped = 插口.ask(load_fake("回文字"), CANSHU, None)

        self.assertEqual(passed, [])
        self.assertEqual(len(dropped), 1)
        self.assertIn("JSON 对象", dropped[0][1])

    def test_request_id_mismatch(self):
        """方案的 request_id 和参数单对不上：全部不要。"""
        chef = load_fake("好的")
        original = chef.teach

        def tampered(canshu, llm):
            result = original(canshu, llm)
            result["request_id"] = "别的单"
            return result

        chef.teach = tampered

        passed, dropped = 插口.ask(chef, CANSHU, None)

        self.assertEqual(passed, [])
        self.assertEqual(len(dropped), 1)
        self.assertIn("request_id", dropped[0][1])

    def test_range_mismatch(self):
        """天数、饮、法对不上的方案，各自被丢掉。"""
        passed, dropped = 插口.ask(load_fake("range不对"), CANSHU, None)

        self.assertEqual(passed, [])
        self.assertEqual(len(dropped), 3)
        reasons = [reason for _, reason in dropped]
        self.assertTrue(any("天数" in reason for reason in reasons))
        self.assertTrue(any("没有饮" in reason for reason in reasons))
        self.assertTrue(any("做法" in reason for reason in reasons))

    def test_meal_mismatch(self):
        """餐数对不上的方案被丢掉，其余照用。"""
        passed, dropped = 插口.ask(load_fake("餐不对"), CANSHU, None)

        self.assertEqual(len(passed), 2)
        self.assertEqual(len(dropped), 1)
        self.assertIn("餐", dropped[0][1])

    def test_skill_json_fields_are_checked(self):
        """说明书不合格的四种情况都报错，说清哪里不对。"""
        cases = {
            "缺字段": {"name": "x"},
            "kind 不对": {
                "name": "x",
                "kind": "技能",
                "author": "测试",
                "entry": "main.py",
                "reads": ["参数单"],
                "writes": ["方案"],
                "knowledge": [],
            },
            "writes 不对": {
                "name": "x",
                "kind": "厨神",
                "author": "测试",
                "entry": "main.py",
                "reads": ["参数单"],
                "writes": ["本人库"],
                "knowledge": [],
            },
        }
        for name, skill in cases.items():
            with self.subTest(name=name):
                folder = tempfile.TemporaryDirectory()
                self.addCleanup(folder.cleanup)
                with open(
                    os.path.join(folder.name, "skill.json"), "w", encoding="utf-8"
                ) as handle:
                    json.dump(skill, handle, ensure_ascii=False)
                with open(
                    os.path.join(folder.name, "main.py"), "w", encoding="utf-8"
                ) as handle:
                    handle.write("def teach(canshu, llm):\n    return {}\n")
                with self.assertRaises(ValueError):
                    插口.load(folder.name)


if __name__ == "__main__":
    unittest.main()
