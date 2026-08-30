# -*- coding: utf-8 -*-
"""
mock_data.py —— 生成模拟 POI 数据（开发/测试用）
==================================================
在没有高德 API key 或不想消耗免费配额时，
用本脚本生成一份杭州/宁波等地的人造 POI 数据，
让评分引擎和 agent 全链路可测。

用法:
  python src/data/mock_data.py
"""
import sys
import random
import math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CATEGORY_PROFILES, TARGET_POI_TYPES, ZHEJIANG_CITIES  # noqa: E402
from data.query import insert_pois  # noqa: E402

random.seed(42)

# 模拟区域中心（杭州/宁波/温州主城区）
CENTERS = [
    {'city': '杭州', 'lng': 120.1552, 'lat': 30.2741, 'name': '文三路'},
    {'city': '杭州', 'lng': 120.2108, 'lat': 30.2460, 'name': '滨江区长河'},
    {'city': '宁波', 'lng': 121.5497, 'lat': 29.8683, 'name': '鄞州区万达'},
    {'city': '温州', 'lng': 120.6994, 'lat': 28.0013, 'name': '鹿城区'},
]

# 生成点：绕中心随机散布（高斯分布, ~1.5km 范围）
def gen_points(center, n, radius_km=1.5):
    pts = []
    for _ in range(n):
        ang = random.uniform(0, 2 * math.pi)
        r = random.gauss(0, radius_km / 2.5)
        dlat = r * math.cos(ang) / 111.0
        dlng = r * math.sin(ang) / (111.0 * math.cos(center['lat'] / 180 * math.pi))
        pts.append((center['lng'] + dlng, center['lat'] + dlat))
    return pts


def generate():
    rows = []
    type_kw = {
        '学校': ['大学', '职业技术学院', '中学'],
        '办公': ['写字楼', '商务大厦', '产业园'],
        '商圈': ['购物中心', '商场', '商业街'],
        '社区': ['小区', '公寓', '住宅区'],
        '通勤': ['地铁站', '公交站'],
    }
    for center in CENTERS:
        # 竞品（每品类 2~10 家）
        for cat, prof in CATEGORY_PROFILES.items():
            n = random.randint(2, 10)
            for lng, lat in gen_points(center, n):
                rows.append({
                    'city': center['city'], 'adname': center['name'],
                    'category': cat, 'poi_type': prof['poi_keywords'][0],
                    'name': f"{cat}店-{random.randint(100, 999)}",
                    'address': f"{center['city']}{center['name']}某街{random.randint(1, 99)}号",
                    'lng': lng, 'lat': lat,
                })
        # 客群配套
        for label, kws in TARGET_POI_TYPES.items():
            n = random.randint(4, 16)
            for lng, lat in gen_points(center, n):
                rows.append({
                    'city': center['city'], 'adname': center['name'],
                    'category': label, 'poi_type': random.choice(type_kw[label]),
                    'name': f"{random.choice(type_kw[label])}-{random.randint(1, 999)}",
                    'address': f"{center['city']}{center['name']}",
                    'lng': lng, 'lat': lat,
                })
    insert_pois(rows)
    print(f'已生成 {len(rows)} 条模拟 POI 数据 -> data/zj_poi.db')
    return rows


if __name__ == '__main__':
    generate()
