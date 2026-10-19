#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本人库和“记”的测试。全部用假的大模型，不连网。运行：

    python -m unittest 测试/测记.py

设了 SHISHEN_LLM_KEY（以及 SHISHEN_LLM_BASE_URL、SHISHEN_LLM_MODEL）时，
最后那条连网测试会真的跑一次；没设就自动跳过。
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock

# 从仓库根导入 食神/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from 食神 import 本人库, 记  # noqa: E402


class FakeLLM:
    """假的大模型：记下收到的提示词，固定回一段文字。"""

    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.reply


def _json(items):
    return json.dumps(items, ensure_ascii=False)


class TestJi(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {"SHISHEN_HOME": self.home.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.home.cleanup)

    def test_empty_library_adds_two_people(self):
        """空本人库：假 llm 说加两个人、各设体质。"""
        text = "我爸和我都是阴虚火旺，没什么忌口"
        reply = _json(
            [
                {"op": "add_person", "name": "爸爸"},
                {"op": "add_person", "name": "我"},
                {
                    "op": "set",
                    "person": "爸爸",
                    "field": "constitution",
                    "value": ["阴虚", "热"],
                },
                {
                    "op": "set",
                    "person": "我",
                    "field": "constitution",
                    "value": ["阴虚", "热"],
                },
            ]
        )

        data, message = 记.ji(text, 本人库.empty(), FakeLLM(reply))

        people = {person["name"]: person for person in data["people"]}
        self.assertEqual(set(people), {"爸爸", "我"})
        for person in people.values():
            self.assertEqual(person["constitution"], ["阴虚", "热"])
            self.assertTrue(any(note["text"] == text for note in person["notes"]))
        self.assertIn("阴虚", message)

    def test_word_outside_vocabulary_is_blocked(self):
        """假 llm 给一个不在词表里的体质：挡下，原话进 note。"""
        text = "我最近上火"
        reply = _json(
            [
                {"op": "add_person", "name": "爸爸"},
                {
                    "op": "set",
                    "person": "爸爸",
                    "field": "constitution",
                    "value": ["上火"],
                },
            ]
        )

        data, _ = 记.ji(text, 本人库.empty(), FakeLLM(reply))

        person = data["people"][0]
        self.assertEqual(person["constitution"], [])
        self.assertTrue(any(note["text"] == text for note in person["notes"]))

        # 直接看代码那一半挡下的理由
        _, blocked = 本人库.apply(
            data,
            [
                {
                    "op": "set",
                    "person": "爸爸",
                    "field": "constitution",
                    "value": ["上火"],
                }
            ],
        )
        self.assertEqual(len(blocked), 1)
        self.assertIn("词表", blocked[0][1])

    def test_pantry_item_not_in_bencao_is_blocked(self):
        """假 llm 给一个本草库里没有的存货：挡下，原话进 note。"""
        text = "家里还有一百克那个东西"
        reply = _json([{"op": "pantry", "item": "buzai", "qty": 100, "unit": "g"}])

        data, _ = 记.ji(text, 本人库.empty(), FakeLLM(reply))

        self.assertEqual(data["pantry"], [])
        owner = data["people"][0]
        self.assertEqual(owner["name"], "主人")
        self.assertTrue(any(note["text"] == text for note in owner["notes"]))

        _, blocked = 本人库.apply(
            本人库.empty(),
            [{"op": "pantry", "item": "buzai", "qty": 100, "unit": "g"}],
        )
        self.assertEqual(len(blocked), 1)
        self.assertIn("本草库", blocked[0][1])

    def test_unknown_op_is_blocked_others_applied(self):
        """不认识的 op 挡下，其他合格的照样写进去。"""
        text = "把我妈也加上"
        reply = _json(
            [
                {"op": "delete_person", "person": "爸爸"},
                {"op": "add_person", "name": "妈妈"},
            ]
        )

        data, _ = 记.ji(text, 本人库.empty(), FakeLLM(reply))

        self.assertEqual([person["name"] for person in data["people"]], ["妈妈"])
        self.assertTrue(
            any(note["text"] == text for note in data["people"][0]["notes"])
        )

    def test_non_json_reply_becomes_note(self):
        """大模型回来的不是 JSON：整句当 note，不报错。"""
        text = "最近睡得不太好"

        data, message = 记.ji(text, 本人库.empty(), FakeLLM("好的，我记下了。"))

        self.assertEqual(len(data["people"]), 1)
        self.assertEqual(data["people"][0]["name"], "主人")
        self.assertEqual(data["people"][0]["notes"][0]["text"], text)
        self.assertEqual(message, "记下了。")

    def test_save_load_roundtrip_and_home(self):
        """save 以后 load 回来一样；SHISHEN_HOME 能改位置。"""
        data = 本人库.empty()
        data["people"].append(
            {
                "id": "p1",
                "name": "阿禾",
                "constitution": ["阴虚"],
                "notes": [],
                "at": "2026-10-18T19:00:00-07:00",
            }
        )

        本人库.save(data)
        self.assertTrue(
            os.path.isfile(os.path.join(self.home.name, "本人库.json"))
        )
        self.assertEqual(本人库.load(), data)

        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        with mock.patch.dict(os.environ, {"SHISHEN_HOME": other.name}):
            本人库.save(data)
            self.assertTrue(os.path.isfile(os.path.join(other.name, "本人库.json")))
            self.assertEqual(本人库.load(), data)

    def test_every_applied_change_has_at_with_offset(self):
        """每条写进去的改动都带当地时刻，ISO 8601，带时区偏移。"""
        text = "我住在圣荷西，家里还有枸杞"
        reply = _json(
            [
                {"op": "add_person", "name": "我"},
                {
                    "op": "set",
                    "person": "我",
                    "field": "constitution",
                    "value": ["阴虚"],
                },
                {
                    "op": "place",
                    "name": "圣荷西",
                    "lat": 37.33,
                    "lon": -121.89,
                    "tz": "America/Los_Angeles",
                },
                {"op": "pantry", "item": "gouqizi", "qty": 200, "unit": "g"},
            ]
        )

        data, _ = 记.ji(text, 本人库.empty(), FakeLLM(reply))

        person = data["people"][0]
        stamps = [
            person["at"],
            data["place"]["at"],
            data["pantry"][0]["at"],
        ] + [note["at"] for note in person["notes"]]
        self.assertTrue(stamps)
        for stamp in stamps:
            moment = datetime.fromisoformat(stamp)
            self.assertIsNotNone(moment.utcoffset(), "{} 没有时区偏移".format(stamp))

    def test_bad_place_and_unknown_person_are_blocked(self):
        """时区不合法、找不到人，都挡下。"""
        _, blocked = 本人库.apply(
            本人库.empty(),
            [
                {"op": "place", "name": "火星", "lat": 1, "lon": 1, "tz": "Mars/Base"},
                {"op": "note", "person": "没有这个人", "text": "随便说一句"},
            ],
        )

        self.assertEqual(len(blocked), 2)
        self.assertIn("时区", blocked[0][1])
        self.assertIn("找不到", blocked[1][1])

    def test_prompt_has_word_list_and_only_people_id_and_name(self):
        """提示词里有词表全文、现有人的 id 和 name，没有人的别的内容。"""
        data = 本人库.empty()
        data["people"].append(
            {
                "id": "p1",
                "name": "阿禾",
                "constitution": ["阴虚"],
                "taste": ["清淡"],
                "avoid": ["辛"],
                "notes": [{"at": "2026-10-18T19:00:00-07:00", "text": "这是一句不该出现在提示词里的秘密"}],
                "at": "2026-10-18T19:00:00-07:00",
            }
        )
        llm = FakeLLM("[]")

        记.ji("随便说一句", data, llm)

        prompt = llm.prompts[0]
        self.assertIn("阴虚", prompt)  # 词表全文
        self.assertIn("平和", prompt)
        self.assertIn("p1", prompt)
        self.assertIn("阿禾", prompt)
        self.assertNotIn("秘密", prompt)
        self.assertIn("随便说一句", prompt)
        self.assertNotIn("{{", prompt)

    def test_fenced_json_is_still_parsed(self):
        """模型把 JSON 包在代码块里，也照样认。"""
        reply = "```json\n" + _json([{"op": "add_person", "name": "妈妈"}]) + "\n```"

        data, _ = 记.ji("把我妈也加上", 本人库.empty(), FakeLLM(reply))

        self.assertEqual([person["name"] for person in data["people"]], ["妈妈"])

    def test_command_line_writes_library(self):
        """命令行这条：读本人库、记一句、存回去、打印回话。"""
        reply = _json(
            [
                {"op": "add_person", "name": "爸爸"},
                {"op": "add_person", "name": "我"},
                {
                    "op": "set",
                    "person": "爸爸",
                    "field": "constitution",
                    "value": ["阴虚", "热"],
                },
            ]
        )
        buffer = io.StringIO()

        with mock.patch.object(记, "http_llm", FakeLLM(reply)):
            with contextlib.redirect_stdout(buffer):
                code = 记.main(["我爸和我都是阴虚火旺"])

        self.assertEqual(code, 0)
        saved = 本人库.load()
        self.assertEqual({person["name"] for person in saved["people"]}, {"爸爸", "我"})
        self.assertEqual(saved["people"][0]["constitution"], ["阴虚", "热"])
        self.assertTrue(buffer.getvalue().strip())

    def test_add_person_can_carry_constitution(self):
        """大模型把体质、忌口直接放进 add_person 也要收下。"""
        text = "我爸是阴虚火旺，忌辛辣"
        reply = _json(
            [
                {
                    "op": "add_person",
                    "name": "爸爸",
                    "constitution": ["阴虚", "热"],
                    "avoid": ["辛"],
                }
            ]
        )

        data, _ = 记.ji(text, 本人库.empty(), FakeLLM(reply))

        person = data["people"][0]
        self.assertEqual(person["name"], "爸爸")
        self.assertEqual(person["constitution"], ["阴虚", "热"])
        self.assertEqual(person["avoid"], ["辛"])

    def test_add_person_with_bad_constitution_is_blocked(self):
        """add_person 里的体质不在词表，整条挡下，原话还是进 note。"""
        text = "我爸最近上火"
        reply = _json(
            [{"op": "add_person", "name": "爸爸", "constitution": ["上火"]}]
        )

        data, _ = 记.ji(text, 本人库.empty(), FakeLLM(reply))

        self.assertFalse(any(person["name"] == "爸爸" for person in data["people"]))
        self.assertTrue(
            any(
                note["text"] == text
                for person in data["people"]
                for note in person["notes"]
            )
        )

    @unittest.skipUnless(
        os.environ.get("SHISHEN_LLM_KEY"), "没有设置 SHISHEN_LLM_KEY，跳过连网测试"
    )
    def test_real_llm(self):
        """真的连一次模型，跑任务卡第 3 节那句话。"""
        text = "我爸和我都是阴虚火旺，没什么忌口，我们住在圣荷西"

        data, _ = 记.ji(text, 本人库.empty(), 记.http_llm)

        self.assertEqual(len(data["people"]), 2)
        for person in data["people"]:
            self.assertEqual(person["constitution"], ["阴虚", "热"])
        self.assertEqual(data["place"]["tz"], "America/Los_Angeles")


if __name__ == "__main__":
    unittest.main()
