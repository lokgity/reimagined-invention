# -*- coding: utf-8 -*-
"""
patch_data.py —— 定向补抓数据缺口
==================================
只补抓审计发现缺口较大的 城市×品类，避免浪费配额。

缺口清单（来自 _audit.py）:
  金华/便利店(121), 舟山/便利店(75), 舟山/学校(115), 舟山/商圈(134),
  湖州/学校(202), 丽水/办公(199), 丽水/商圈(233)

用法: python src/data/patch_data.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data.fetch_poi import search_poi  # noqa: E402
from data.query import insert_pois  # noqa: E402

# 补抓任务: (城市, 品类, 关键词列表)
PATCH_TASKS = [
    ('金华', '便利店', ['便利店', '超市']),
    ('舟山', '便利店', ['便利店', '超市']),
    ('舟山', '学校', ['大学', '学院', '中学', '小学']),
    ('舟山', '商圈', ['购物中心', '商场', '商业街', '步行街']),
    ('湖州', '学校', ['大学', '学院', '中学', '小学']),
    ('丽水', '办公', ['写字楼', '商务大厦', '产业园']),
    ('丽水', '商圈', ['购物中心', '商场', '商业街']),
    ('金华', '学校', ['大学', '学院', '中学']),
    ('湖州', '商圈', ['购物中心', '商场']),
]


def patch():
    total = 0
    for city, category, kws in PATCH_TASKS:
        for kw in kws:
            try:
                rows, _ = search_poi(kw, city, max_pages=8)
            except Exception as e:
                print(f'[跳过] {city}/{category}/{kw}: {e}')
                time.sleep(2)
                continue
            for r in rows:
                r['category'] = category
            if rows:
                insert_pois(rows)
                total += len(rows)
            print(f'[{city}] {category}/{kw}: 入库 {len(rows)}')
            time.sleep(0.5)
    print(f'\n补抓完成，共入库 {total} 条')


if __name__ == '__main__':
    patch()
