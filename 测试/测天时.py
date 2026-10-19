#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""天时的测试。运行：

    python -m unittest 测试/测天时.py
"""

import os
import sys
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

# 从仓库根导入 食神/天时.py
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from 食神.天时 import tianshi  # noqa: E402

LOS_ANGELES = ZoneInfo("America/Los_Angeles")
SHANGHAI = ZoneInfo("Asia/Shanghai")

# 湾区：纬度 37.33，经度 -121.89
BAY = (37.33, -121.89)
# 北京：纬度 39.90，经度 116.40
BEIJING = (39.90, 116.40)


def _minutes(clock):
    """把 "11:53" 换成一天里的第几分钟。"""
    hour, minute = clock.split(":")
    return int(hour) * 60 + int(minute)


class TestTianshi(unittest.TestCase):
    def bay_area(self, when):
        return tianshi(*BAY, "America/Los_Angeles", when)

    def beijing(self, when):
        return tianshi(*BEIJING, "Asia/Shanghai", when)

    def test_bay_area_autumn(self):
        """湾区 2026-10-18 中午：寒露，下一个霜降，秋。"""
        result = self.bay_area(datetime(2026, 10, 18, 12, 0, tzinfo=LOS_ANGELES))

        self.assertEqual(result["solar_term"], "寒露")
        self.assertEqual(result["next_solar_term"]["name"], "霜降")
        self.assertEqual(result["season"], "秋")
        self.assertEqual(result["date"], "2026-10-18")
        self.assertEqual(result["place"], {
            "lat": 37.33,
            "lon": -121.89,
            "tz": "America/Los_Angeles",
        })

    def test_wu_clock(self):
        """同一天，午时的钟表起点在 11:51 到 11:55 之间。"""
        result = self.bay_area(datetime(2026, 10, 18, 12, 0, tzinfo=LOS_ANGELES))
        meals = result["meals"]

        self.assertEqual(meals["午"]["shichen"], "午时")
        start = _minutes(meals["午"]["clock"].split("-")[0])
        self.assertGreaterEqual(start, 11 * 60 + 51)
        self.assertLessEqual(start, 11 * 60 + 55)

        # 早、晚也一并核一下：辰时、酉时，各两个时辰长
        self.assertEqual(meals["早"]["shichen"], "辰时")
        self.assertEqual(meals["晚"]["shichen"], "酉时")
        for meal in meals.values():
            start, end = meal["clock"].split("-")
            self.assertEqual((_minutes(end) - _minutes(start)) % (24 * 60), 120)

    def test_term_crosses_the_date_line(self):
        """立春在北京是 2 月 4 日，在湾区还是 2 月 3 日。

        交节以前，湾区的 solar_term 还是上一个节气（大寒）；交节以后才是立春。
        """
        before = datetime(2027, 2, 3, 10, 0, tzinfo=LOS_ANGELES)
        after = datetime(2027, 2, 3, 20, 0, tzinfo=LOS_ANGELES)

        # 这两个时刻在北京都是 2 月 4 日，在湾区都是 2 月 3 日
        for moment in (before, after):
            self.assertEqual(moment.astimezone(SHANGHAI).date().isoformat(), "2027-02-04")
            self.assertEqual(moment.date().isoformat(), "2027-02-03")

        # 立春的当地时刻也落在湾区的 2 月 3 日
        at = self.bay_area(before)["next_solar_term"]
        self.assertEqual(at["name"], "立春")
        self.assertEqual(at["at"][:10], "2027-02-03")

        self.assertEqual(self.bay_area(before)["solar_term"], "大寒")
        self.assertEqual(self.bay_area(after)["solar_term"], "立春")

    def test_beijing_same_moment(self):
        """北京同一时刻：节气一样，时辰的钟表时间不一样。"""
        bay_moment = datetime(2026, 10, 18, 12, 0, tzinfo=LOS_ANGELES)
        beijing_moment = bay_moment.astimezone(SHANGHAI)

        bay = self.bay_area(bay_moment)
        beijing = self.beijing(beijing_moment)

        self.assertEqual(beijing["solar_term"], bay["solar_term"])
        self.assertEqual(beijing["next_solar_term"]["name"], bay["next_solar_term"]["name"])
        self.assertNotEqual(beijing["meals"]["午"]["clock"], bay["meals"]["午"]["clock"])
        # 两地都是午时（时辰按各自地方的真太阳时算）
        self.assertEqual(beijing["meals"]["午"]["shichen"], "午时")

    def test_almanac(self):
        """天时单里带当地日期的干支日和宜忌。"""
        result = self.bay_area(datetime(2026, 10, 18, 12, 0, tzinfo=LOS_ANGELES))
        almanac = result["almanac"]

        self.assertIsInstance(almanac["ganzhi_day"], str)
        self.assertTrue(almanac["ganzhi_day"])
        self.assertIsInstance(almanac["yi"], list)
        self.assertIsInstance(almanac["ji"], list)
        self.assertTrue(almanac["yi"])
        self.assertTrue(almanac["ji"])


if __name__ == "__main__":
    unittest.main()
