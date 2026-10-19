#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抽参的测试。运行：

    python -m unittest 测试/测抽参.py
"""

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from 食神.抽参 import chouchan  # noqa: E402
from 食神 import 抽参  # noqa: E402

with open(os.path.join(ROOT, "测试", "样例本人库.json"), encoding="utf-8") as _handle:
    SAMPLE = json.load(_handle)

TIANSHI = {
    "date": "2026-10-18",
    "place": {"lat": 37.33, "lon": -121.89, "tz": "America/Los_Angeles"},
    "solar_term": "寒露",
    "next_solar_term": {"name": "霜降", "at": "2026-10-23T02:37:57-07:00"},
    "season": "秋",
    "almanac": {"ganzhi_day": "乙丑", "yi": ["解除", "祭祀"], "ji": ["嫁娶", "开市"]},
    "meals": {},
}

FORBIDDEN_KEYS = {
    "name",
    "birth_year",
    "notes",
    "lat",
    "lon",
    "tz",
    "feelings",
    "saved",
    "pantry",
    "history",
}


def all_keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from all_keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from all_keys(item)


def empty_library(people=None):
    return {
        "owner": "主人",
        "place": {},
        "people": people or [],
        "feelings": [],
        "saved": [],
        "pantry": [],
        "history": [],
    }


class TestChouchan(unittest.TestCase):
    def test_nothing_personal_leaks(self):
        """任何一层都没有名字、出生年、经纬度这些键，也没有人的名字。"""
        canshu = chouchan(SAMPLE, TIANSHI)

        self.assertEqual(set(all_keys(canshu)) & FORBIDDEN_KEYS, set())
        text = json.dumps(canshu, ensure_ascii=False)
        self.assertNotIn("阿禾", text)
        self.assertNotIn("birth_year", text)

    def test_age_band_boundaries(self):
        """年龄段的每一处边界都要对。"""
        ages = [0, 5, 6, 17, 18, 39, 40, 64, 65, 84, 85, 100]
        expected = [
            "幼儿",
            "幼儿",
            "少年",
            "少年",
            "青年",
            "青年",
            "中年",
            "中年",
            "老年",
            "老年",
            "高龄",
            "高龄",
        ]
        people = [
            {
                "id": "p{}".format(index + 1),
                "name": "人{}".format(index + 1),
                "birth_year": 2026 - age,
                "constitution": [],
                "taste": [],
                "avoid": [],
            }
            for index, age in enumerate(ages)
        ]

        canshu = chouchan(empty_library(people), TIANSHI)

        self.assertEqual(
            [person.get("age_band") for person in canshu["people"]], expected
        )

    def test_no_birth_year_no_age_band(self):
        """没有出生年的人，不给 age_band。"""
        people = [
            {"id": "p1", "name": "阿禾", "constitution": [], "taste": [], "avoid": []}
        ]

        canshu = chouchan(empty_library(people), TIANSHI)

        self.assertNotIn("age_band", canshu["people"][0])

    def test_who_selects_one_person(self):
        """who 只选一个人时，参数单里只有一个人。"""
        canshu = chouchan(SAMPLE, TIANSHI, who=["p2"])

        self.assertEqual(len(canshu["people"]), 1)
        self.assertEqual(canshu["people"][0]["tag"], "甲")
        self.assertEqual(canshu["people"][0]["age_band"], "中年")

    def test_two_runs_differ_only_in_request_id(self):
        """两次抽参，除了 request_id，其余完全一样。"""
        first = chouchan(SAMPLE, TIANSHI)
        second = chouchan(SAMPLE, TIANSHI)

        self.assertNotEqual(first["request_id"], second["request_id"])
        first.pop("request_id")
        second.pop("request_id")
        self.assertEqual(first, second)

    def test_range_passes_through(self):
        """days、meals、drinks 原样放进 range。"""
        canshu = chouchan(SAMPLE, TIANSHI, days=3, meals=("早",), drinks=False)

        self.assertEqual(
            canshu["range"], {"days": 3, "meals": ["早"], "drinks": False}
        )

    def test_tianshi_and_di_only_take_allowed_fields(self):
        """天时只取三项；地方只取 region 和 climate。"""
        canshu = chouchan(SAMPLE, TIANSHI)

        self.assertEqual(
            canshu["tianshi"],
            {
                "solar_term": "寒露",
                "season": "秋",
                "almanac_ji": ["嫁娶", "开市"],
            },
        )
        self.assertEqual(
            canshu["di"],
            {
                "region": "江南",
                "climate": {"humid": "偏潮", "temp": "温和"},
            },
        )

    def test_whitelist_rejects_extra_key(self):
        """组装完的检查：多出白名单以外的键就报错。"""
        bad = {
            "request_id": "x",
            "range": {"days": 7, "meals": ["午"], "drinks": True},
            "people": [{"tag": "甲", "name": "阿禾"}],
            "tianshi": {},
            "di": {},
        }

        with self.assertRaises(ValueError) as caught:
            抽参._check_whitelist(bad)

        self.assertIn("name", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
