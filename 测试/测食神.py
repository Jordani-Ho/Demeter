#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""食神的测试：用假 llm 和样例本人库走完整条，不连网。运行：

    python -m unittest 测试/测食神.py

设了 SHISHEN_LLM_KEY（或 我的食神/设置.env）时，最后一条连网测试会真的跑一次“本周”。
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from 食神 import 食神  # noqa: E402

SAMPLE = os.path.join(ROOT, "测试", "样例本人库.json")

# 机器用的字段，主人那份 Markdown 里一个都不能出现
MACHINE_WORDS = (
    "request_id",
    "plan_id",
    "decision_id",
    "teacher",
    "参数单",
    "plan",
)


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
    """一池合格的菜：汤 5、菜 8、主食 2、饮 5（样例人家能吃的料）。"""
    return {
        "idea": "秋燥偏潮，滋阴润燥，清淡软烂。",
        "dishes": [
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
        ],
        "drinks": [
            drink("雪梨蜂蜜饮", ["xueli", "fengmi"]),
            drink("银耳糖水", ["yiner", "bingtang"], "炖"),
            drink("罗汉果饮", ["luohanguo"]),
            drink("百合饮", ["baihe"]),
            drink("雪梨饮", ["xueli"]),
        ],
    }


class FakeLLM:
    """假的大模型：看提示词是哪一步，回对应的一段。

    记 -> 改动数组；厨神甲 -> 菜池；定夺平手 -> 一行选择。
    """

    def __init__(self, pool=None, changes=None, pick="A｜按近况和口味挑的。"):
        self.pool_text = json.dumps(pool or pool_obj(), ensure_ascii=False)
        self.changes_text = json.dumps(changes or [], ensure_ascii=False)
        self.pick = pick
        self.prompts = []

    def __call__(self, prompt, max_tokens=None):
        self.prompts.append(prompt)
        if "翻译成本人库的改动" in prompt:
            return self.changes_text
        if "出一池菜" in prompt:
            return self.pool_text
        if "请从下面这几套里挑一套" in prompt:
            return self.pick
        return "[]"


class TestShishen(unittest.TestCase):
    def sample_home(self):
        """一间临时本人库：放样例本人库，SHISHEN_HOME 指过去。"""
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        shutil.copy(SAMPLE, os.path.join(folder.name, "本人库.json"))
        patcher = mock.patch.dict(os.environ, {"SHISHEN_HOME": folder.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        return folder.name

    def empty_home(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = mock.patch.dict(os.environ, {"SHISHEN_HOME": folder.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        return folder.name

    def week_text(self, home):
        with open(os.path.join(home, "本周.md"), encoding="utf-8") as handle:
            return handle.read()

    def set_pantry(self, home, entries):
        """改样例本人库的存货，验“家里已经有的单独列”。"""
        path = os.path.join(home, "本人库.json")
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        data["pantry"] = [
            {"item": item, "qty": qty, "unit": "g", "at": "2026-10-18T19:00:00+08:00"}
            for item, qty in entries.items()
        ]
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)

    def test_week_end_to_end(self):
        """假 llm 走完整条：本周.md 生成了，history 写进去了，没有机器字段。"""
        home = self.sample_home()
        self.set_pantry(home, {"xiaomi": 5000})
        out = io.StringIO()

        with contextlib.redirect_stdout(out):
            code = 食神.main(["本周"], llm=FakeLLM())

        self.assertEqual(code, 0)
        self.assertTrue(os.path.isfile(os.path.join(home, "本周.md")))
        text = self.week_text(home)
        self.assertIn("# 本周吃什么", text)
        self.assertIn("这周按这个思路吃", text)
        self.assertIn("为什么定这个", text)
        self.assertIn("**午**", text)
        self.assertIn("**晚**", text)
        self.assertIn("做法：", text)
        self.assertIn("采买清单（按周）", text)
        self.assertIn("**要买**", text)
        self.assertIn("**家里已经有了**", text)
        for word in MACHINE_WORDS:
            self.assertNotIn(word, text, "主人的 Markdown 里不该出现：{}".format(word))
        self.assertIn("已存到", out.getvalue())

        with open(os.path.join(home, "本人库.json"), encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertEqual(len(data["history"]), 1)
        entry = data["history"][0]
        self.assertEqual(len(entry["date"]), 10)
        self.assertTrue(entry["decision_id"])
        self.assertTrue(entry["dishes"])

    def test_week_buy_by_day(self):
        """--买 日：采买清单按天出七张。"""
        home = self.sample_home()

        with contextlib.redirect_stdout(io.StringIO()):
            code = 食神.main(["本周", "--买", "日"], llm=FakeLLM())

        self.assertEqual(code, 0)
        text = self.week_text(home)
        self.assertIn("采买清单（按日）", text)
        self.assertIn("### 第 7 天", text)

    def test_week_not_decided(self):
        """没定成：只说一句“这周没定成”，不报错退出，不写本周.md。"""
        home = self.sample_home()
        pool = pool_obj()
        pool["dishes"] = [one for one in pool["dishes"] if one["kind"] != "汤"]
        out = io.StringIO()

        with contextlib.redirect_stdout(out):
            code = 食神.main(["本周"], llm=FakeLLM(pool=pool))

        self.assertEqual(code, 0)
        self.assertIn("这周没定成", out.getvalue())
        self.assertFalse(os.path.exists(os.path.join(home, "本周.md")))

    def test_ji_command(self):
        """记：一句话进本人库，本人库真的改了。"""
        home = self.empty_home()
        changes = [
            {"op": "add_person", "name": "我爸", "constitution": ["阴虚", "热"]},
            {"op": "add_person", "name": "我", "constitution": ["阴虚", "热"]},
            {
                "op": "place",
                "name": "圣荷西",
                "lat": 37.33,
                "lon": -121.89,
                "tz": "America/Los_Angeles",
                "region": "沿海",
                "climate": {"humid": "偏潮", "temp": "温和"},
            },
        ]
        out = io.StringIO()

        with contextlib.redirect_stdout(out):
            code = 食神.main(
                ["记", "我爸和我都是阴虚火旺，没什么忌口，我们住在圣荷西"],
                llm=FakeLLM(changes=changes),
            )

        self.assertEqual(code, 0)
        self.assertTrue(out.getvalue().strip())
        with open(os.path.join(home, "本人库.json"), encoding="utf-8") as handle:
            data = json.load(handle)
        names = [person["name"] for person in data["people"]]
        self.assertIn("我爸", names)
        self.assertEqual(data["place"]["name"], "圣荷西")

    def test_week_needs_place(self):
        """本人库还是空的：说清楚缺什么，不抛栈。"""
        self.empty_home()
        err = io.StringIO()

        with contextlib.redirect_stderr(err):
            code = 食神.main(["本周"], llm=FakeLLM())

        self.assertEqual(code, 1)
        self.assertIn("没做成", err.getvalue())

    def test_remember_prompt_has_avoid_example(self):
        """记的提示词里有“忌辛辣 → avoid: [辛]”这个例子。"""
        with open(
            os.path.join(ROOT, "食神", "提示词", "记.md"), encoding="utf-8"
        ) as handle:
            prompt = handle.read()

        self.assertIn("忌辛辣", prompt)
        self.assertIn('"辛"', prompt)

    @unittest.skipUnless(
        os.environ.get("SHISHEN_LLM_KEY"), "没有设置 SHISHEN_LLM_KEY，跳过连网测试"
    )
    def test_real_week(self):
        """连网真跑一次“本周”：样例本人库，DeepSeek。"""
        home = self.sample_home()
        out = io.StringIO()

        with contextlib.redirect_stdout(out):
            code = 食神.main(["本周"], llm=食神.http_llm)

        self.assertEqual(code, 0)
        self.assertTrue(os.path.isfile(os.path.join(home, "本周.md")))
        text = self.week_text(home)
        self.assertIn("采买清单（按周）", text)
        for word in MACHINE_WORDS:
            self.assertNotIn(word, text)
        with open(os.path.join(home, "本人库.json"), encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertEqual(len(data["history"]), 1)
        print("\n--- 真跑生成的 本周.md 前 40 行 ---")
        print("\n".join(text.splitlines()[:40]))


if __name__ == "__main__":
    unittest.main()
