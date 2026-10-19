#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大模型设置：先读环境变量，没有就读 我的食神/设置.env。

设置.env 和本人库放在一起（`SHISHEN_HOME` 或默认的 我的食神/），不进仓库。
一行一个 `键=值`，空行和 `#` 开头的行忽略。

对外一个函数：

    get(name, default=None) -> str 或 None
"""

import os

try:  # 作为包导入时（测试里）
    from .本人库 import home as _home
except ImportError:  # 直接跑 食神/ 下的脚本时
    from 本人库 import home as _home

FILE_NAME = "设置.env"


def settings_path():
    """设置文件在哪。"""
    return os.path.join(_home(), FILE_NAME)


def read_file():
    """读设置.env，返回键值对；没有文件就返回空字典。"""
    path = settings_path()
    values = {}
    if not os.path.isfile(path):
        return values
    with open(path, encoding="utf-8-sig") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get(name, default=None):
    """先看环境变量，再看设置.env。"""
    value = os.environ.get(name)
    if value:
        return value
    return read_file().get(name, default)
