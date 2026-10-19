#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定夺的测试。全用写死的方案和本人库，不连网。运行：

    python -m unittest 测试/测定夺.py
"""

from datetime import date, timedelta
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from 食神.定夺 import dingduo, history_entry  # noqa: E402

TODAY = date(2026, 10, 18)

BENCAO = {}
for _name in sorted(os.listdir(os.path.join(ROOT, "本草库"))):
    if not _name.endswith(".json") or _name == "词表.json":
        continue
    with open(os.path.join(ROOT, "本草库", _name), encoding="utf-8") as _handle:
        _entry = json.load(_handle)
    BENCAO[_entry["id"]] = _entry


def make_plan(plan_id, dishes, idea=None):
    """dishes: [[(菜名, [料 id]), ...], ...]，一天一组。"""
    days = []
    for number, day_dishes in enumerate(dishes, start=1):
        meals = []
        for dish_name, ids in day_dishes:
            meals.append(
                {
                    "meal": "晚",
                    "dishes": [
                        {
                            "name": dish_name,
                            "kind": "汤",
                            "ingredients": [
                                {
                                    "item": item_id,
                                    "name": BENCAO[item_id]["name"],
                                    "qty": 10,
                                    "unit": "g",
                                }
                                for item_id in ids
                            ],
                            "method": "煲",
                            "steps": "煲。",
                            "why": "润。",
                            "sources": list(ids),
                        }
                    ],
                }
            )
        days.append({"day": number, "meals": meals})
    return {
        "plan_id": plan_id,
        "idea": idea or "想法",
        "request_id": "req-定夺-1",
        "teacher": "厨神甲",
        "days": days,
    }


def library(people=None, feelings=None, saved=None, history=None):
    return {
        "owner": "主人",
        "place": {},
        "people": people
        or [
            {
                "id": "p1",
                "name": "阿禾",
                "constitution": [],
                "taste": [],
                "avoid": [],
                "notes": [],
            }
        ],
        "feelings": feelings or [],
        "saved": saved or [],
        "pantry": [],
        "history": history or [],
    }


def recent_record(days_ago, dishes):
    return {
        "date": (TODAY - timedelta(days=days_ago)).isoformat(),
        "decision_id": "old",
        "dishes": dishes,
    }


class TestDingduo(unittest.TestCase):
    def test_avoid_id_name_flavour(self):
        """avoid 三种写法都挡：本草 id、中文名、词表里的味。"""
        for term in ("shengjiang", "生姜", "辛"):
            with self.subTest(avoid=term):
                data = library(
                    people=[
                        {
                            "id": "p1",
                            "name": "阿禾",
                            "constitution": [],
                            "taste": [],
                            "avoid": [term],
                            "notes": [],
                        }
                    ]
                )
                with_ginger = make_plan("A", [[("姜汤", ["shengjiang"])]])
                clean = make_plan("B", [[("玉竹汤", ["yuzhu"])]])

                decision, _reason = dingduo([with_ginger, clean], data, TODAY)

                self.assertIsNotNone(decision)
                self.assertEqual(decision["chosen_plan"], "B")

    def test_all_avoided(self):
        """全被 avoid 去掉：没定成。"""
        data = library(
            people=[
                {
                    "id": "p1",
                    "name": "阿禾",
                    "constitution": [],
                    "taste": [],
                    "avoid": ["shengjiang"],
                    "notes": [],
                }
            ]
        )
        plans = [
            make_plan("A", [[("姜汤", ["shengjiang"])]]),
            make_plan("B", [[("姜汤二", ["shengjiang", "yuzhu"])]]),
        ]

        decision, reason = dingduo(plans, data, TODAY)

        self.assertIsNone(decision)
        self.assertIn("没定成", reason)

    def test_too_repetitive_is_removed(self):
        """前三天的菜一半以上是最近三天吃过的：去掉。"""
        data = library(history=[recent_record(1, ["红烧肉", "清蒸鱼"])])
        repetitive = make_plan(
            "A", [[("红烧肉", ["zhushourou"])], [("清蒸鱼", ["jiyu"])]]
        )
        fresh = make_plan("B", [[("玉竹汤", ["yuzhu"])], [("雪梨汤", ["xueli"])]])

        decision, _reason = dingduo([repetitive, fresh], data, TODAY)

        self.assertIsNotNone(decision)
        self.assertEqual(decision["chosen_plan"], "B")

    def test_if_all_repetitive_this_rule_is_skipped(self):
        """全被重复这一条去掉，这一条就不算，回到上一步剩下的。"""
        data = library(history=[recent_record(2, ["红烧肉", "清蒸鱼"])])
        first = make_plan(
            "A", [[("红烧肉", ["zhushourou"])], [("清蒸鱼", ["jiyu"])]]
        )
        second = make_plan(
            "B", [[("红烧肉", ["zhushourou"])], [("清蒸鱼", ["jiyu"])]]
        )

        decision, _reason = dingduo([first, second], data, TODAY)

        self.assertIsNotNone(decision)
        self.assertEqual(decision["chosen_plan"], "A")

    def test_likes_and_saves_win(self):
        """点过赞、收藏过的菜多的方案胜出。"""
        data = library(
            feelings=[{"at": "...", "kind": "like", "item": "玉竹汤"}],
            saved=[{"at": "...", "item": "雪梨汤"}],
        )
        plain = make_plan("A", [[("别的汤", ["yuzhu"])]])
        liked = make_plan(
            "B", [[("玉竹汤", ["yuzhu"])], [("雪梨汤", ["xueli"])]]
        )

        decision, reason = dingduo([plain, liked], data, TODAY)

        self.assertEqual(decision["chosen_plan"], "B")
        self.assertIn("点过赞", reason)

    def test_tie_without_llm_takes_first(self):
        """平手又没有大模型：取第一个，理由用方案的 idea，不说机器的话。"""
        data = library()
        first = make_plan("A", [[("玉竹汤", ["yuzhu"])]], idea="秋燥润一点。")
        second = make_plan("B", [[("雪梨汤", ["xueli"])]])

        decision, reason = dingduo([first, second], data, TODAY)

        self.assertEqual(decision["chosen_plan"], "A")
        self.assertEqual(reason, "秋燥润一点。")
        for word in ("平手", "第一套", "先定"):
            self.assertNotIn(word, reason)

    def test_tie_with_bad_llm_reply_uses_idea(self):
        """大模型回的格式不对：取第一个，理由用方案的 idea。"""
        data = library()
        first = make_plan("A", [[("玉竹汤", ["yuzhu"])]], idea="清淡平补。")
        second = make_plan("B", [[("雪梨汤", ["xueli"])]])

        decision, reason = dingduo(
            [first, second], data, TODAY, llm=lambda prompt: "我也不知道选哪个"
        )

        self.assertEqual(decision["chosen_plan"], "A")
        self.assertEqual(reason, "清淡平补。")

    def test_reason_never_machine_words(self):
        """大模型给的“理由”里带机器的话：换成方案的 idea。"""
        data = library()
        plans = [
            make_plan("A", [[("玉竹汤", ["yuzhu"])]], idea="润燥。"),
            make_plan("B", [[("雪梨汤", ["xueli"])]], idea="清润。"),
        ]

        decision, reason = dingduo(
            plans, data, TODAY, llm=lambda prompt: "A｜平手，先定第一套。"
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision["chosen_plan"], "A")
        self.assertEqual(reason, "润燥。")

    def test_tie_with_llm(self):
        """平手有大模型：用它的选择和理由。"""
        data = library()
        first = make_plan("A", [[("玉竹汤", ["yuzhu"])]])
        second = make_plan("B", [[("雪梨汤", ["xueli"])]])
        prompts = []

        def fake_llm(prompt):
            prompts.append(prompt)
            return "B｜近况偏燥，选润一点的。"

        decision, reason = dingduo([first, second], data, TODAY, llm=fake_llm)

        self.assertEqual(decision["chosen_plan"], "B")
        self.assertEqual(reason, "近况偏燥，选润一点的。")
        self.assertTrue(prompts)
        self.assertIn("方案 B", prompts[0])

    def test_decision_takes_request_id_and_teacher_from_plan(self):
        """决定里的 request_id、teacher 从放行的方案里取。"""
        data = library()
        first = make_plan("A", [[("玉竹汤", ["yuzhu"])]])
        second = make_plan("B", [[("雪梨汤", ["xueli"])]])

        decision, _reason = dingduo([first, second], data, TODAY)

        self.assertEqual(decision["request_id"], "req-定夺-1")
        self.assertEqual(decision["teacher"], "厨神甲")
        self.assertEqual(decision["plan"]["request_id"], "req-定夺-1")

    def test_history_entry(self):
        """history_entry 的格式对：日期、决定 id、菜名。"""
        data = library()
        plan = make_plan(
            "A", [[("玉竹汤", ["yuzhu"])], [("雪梨汤", ["xueli"])]]
        )

        decision, _reason = dingduo([plan], data, TODAY)
        entry = history_entry(decision, TODAY)

        self.assertEqual(entry["date"], "2026-10-18")
        self.assertEqual(entry["decision_id"], decision["decision_id"])
        self.assertEqual(entry["dishes"], ["玉竹汤", "雪梨汤"])


if __name__ == "__main__":
    unittest.main()
