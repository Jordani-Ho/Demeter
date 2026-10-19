#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大模型设置的测试。不连网。运行：

    python -m unittest 测试/测设置.py
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from 食神 import 设置, 记  # noqa: E402


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class TestSettings(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        env = {
            "SHISHEN_HOME": self.home.name,
            "SHISHEN_LLM_BASE_URL": "",
            "SHISHEN_LLM_KEY": "",
            "SHISHEN_LLM_MODEL": "",
        }
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_settings(self, lines):
        with open(
            os.path.join(self.home.name, "设置.env"), "w", encoding="utf-8"
        ) as handle:
            handle.write("\n".join(lines) + "\n")

    def test_environment_wins(self):
        """环境变量优先于设置.env。"""
        self.write_settings(["SHISHEN_LLM_MODEL=文件里的"])
        with mock.patch.dict(os.environ, {"SHISHEN_LLM_MODEL": "环境里的"}):
            self.assertEqual(设置.get("SHISHEN_LLM_MODEL"), "环境里的")

    def test_file_is_used(self):
        """没有环境变量时读设置.env。"""
        self.write_settings(
            [
                "# 注释",
                "",
                "SHISHEN_LLM_BASE_URL=https://api.deepseek.com",
                "SHISHEN_LLM_KEY=sk-测试",
            ]
        )

        self.assertEqual(设置.get("SHISHEN_LLM_BASE_URL"), "https://api.deepseek.com")
        self.assertEqual(设置.get("SHISHEN_LLM_KEY"), "sk-测试")
        self.assertEqual(设置.get("SHISHEN_LLM_MODEL"), None)
        self.assertEqual(设置.get("SHISHEN_LLM_MODEL", "默认"), "默认")

    def test_http_llm_uses_settings_and_max_tokens(self):
        """记.http_llm 用设置.env 里的三个值，并且把 max_tokens 传下去。"""
        self.write_settings(
            [
                "SHISHEN_LLM_BASE_URL=https://api.deepseek.com",
                "SHISHEN_LLM_KEY=sk-测试",
                "SHISHEN_LLM_MODEL=deepseek-chat",
            ]
        )
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["max_tokens"] = None
            return FakeResponse(
                {"choices": [{"message": {"content": "好的"}}]}
            )

        with mock.patch("食神.记.urllib.request.urlopen", side_effect=fake_urlopen):
            answer = 记.http_llm("你好", max_tokens=6000)

        self.assertEqual(answer, "好的")
        self.assertEqual(captured["url"], "https://api.deepseek.com/chat/completions")
        self.assertEqual(captured["body"]["model"], "deepseek-chat")
        self.assertEqual(captured["body"]["max_tokens"], 6000)


if __name__ == "__main__":
    unittest.main()
