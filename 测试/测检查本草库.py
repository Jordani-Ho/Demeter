#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查本草库脚本的测试：aliases 的类型和重复。运行：

    python -m unittest 测试/测检查本草库.py
"""

import contextlib
import copy
import importlib.util
import io
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

BENCAO_DIR = os.path.join(ROOT, "本草库")
SCRIPT = os.path.join(ROOT, "测试", "检查本草库.py")


def load_script():
    spec = importlib.util.spec_from_file_location("jiancha_bencao", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_entry(name):
    with open(os.path.join(BENCAO_DIR, name), encoding="utf-8-sig") as handle:
        return json.load(handle)


class TestAliases(unittest.TestCase):
    def setUp(self):
        self.module = load_script()
        self.words, problems = self.module.load_word_list(BENCAO_DIR)
        self.assertIsNotNone(self.words, problems)
        self.yiyiren = load_entry("yiyiren.json")
        self.gouqizi = load_entry("gouqizi.json")
        self.entries_by_id = {
            "yiyiren": self.yiyiren,
            "gouqizi": self.gouqizi,
        }

    def check(self, data):
        return self.module.check_entry(
            "yiyiren.json",
            data,
            set(self.entries_by_id),
            self.words,
            self.entries_by_id,
        )

    def test_real_aliases_pass(self):
        """真条目（薏苡仁带“薏米”“薏仁”）没有 aliases 问题。"""
        problems = self.check(copy.deepcopy(self.yiyiren))

        self.assertFalse([item for item in problems if "aliases" in item], problems)

    def test_aliases_must_be_array(self):
        """aliases 不是数组：报出来。"""
        data = copy.deepcopy(self.yiyiren)
        data["aliases"] = "薏米"

        problems = self.check(data)

        self.assertTrue(
            any("aliases" in item and "数组" in item for item in problems), problems
        )

    def test_alias_must_be_string(self):
        """别名里混了数：报出来。"""
        data = copy.deepcopy(self.yiyiren)
        data["aliases"] = ["薏米", 5]

        problems = self.check(data)

        self.assertTrue(
            any("aliases" in item and "字符串" in item for item in problems), problems
        )

    def test_alias_must_not_be_empty(self):
        """别名是空字符串：报出来。"""
        data = copy.deepcopy(self.yiyiren)
        data["aliases"] = [""]

        problems = self.check(data)

        self.assertTrue(
            any("aliases" in item and "空字符串" in item for item in problems),
            problems,
        )

    def test_alias_clashing_with_other_entry_name(self):
        """别名和别的条目的名字重复：报出来。"""
        data = copy.deepcopy(self.yiyiren)
        data["aliases"] = ["枸杞子"]

        problems = self.check(data)

        self.assertTrue(
            any(
                "aliases" in item and "枸杞子" in item and "gouqizi" in item
                for item in problems
            ),
            problems,
        )

    def test_alias_clashing_with_other_entry_alias(self):
        """别名和别的条目的别名重复：报出来。"""
        data = copy.deepcopy(self.yiyiren)
        data["aliases"] = ["枸杞"]

        problems = self.check(data)

        self.assertTrue(
            any("aliases" in item and "枸杞" in item for item in problems), problems
        )

    def test_alias_written_twice(self):
        """同一条目的别名写了两次：报出来。"""
        data = copy.deepcopy(self.yiyiren)
        data["aliases"] = ["薏米", "薏米"]

        problems = self.check(data)

        self.assertTrue(
            any("aliases" in item and "写了两次" in item for item in problems),
            problems,
        )

    def test_real_library_still_passes(self):
        """整库检查还是全过。"""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.module.main(["检查本草库.py", BENCAO_DIR])

        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("本草库合格", out.getvalue())


if __name__ == "__main__":
    unittest.main()
