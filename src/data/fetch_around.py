# -*- coding: utf-8 -*-
"""
fetch_around.py —— 高德周边搜索补充抓取
========================================
针对特定坐标（如大学城/商圈）用 around API 精确抓取周边 POI，
弥补关键词搜索的覆盖缺口。

用法: python src/data/fetch_around.py
"""
import sys
import time
import json
import urllib.parse
import urllib.request
import ssl
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import AMAP_KEY, AMAP_SECRET  # noqa: E402
from data.query import insert_pois  # noqa: E402

CTX = ssl.create_default_context()


def amap_sign(params: dict) -> str:
    if not AMAP_SECRET:
        return ''
    ordered = '&'.join(f'{k}={params[k]}' for k in sorted(params))
    return __import__('hashlib').sha256((ordered + AMAP_SECRET).encode('utf-8')).hexdigest().upper()


def amap_url(path: str, params: dict) -> str:
    p = dict(params)
    p['key'] = AMAP_KEY
    sig = amap_sign(p)
    if sig:
        p['sig'] = sig
    return f'https://restapi.amap.com{path}?{urllib.parse.urlencode(p)}'


def http_get(url, timeout=15, retries=3):
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception as e:
            last_err = e
            print(f'    [retry {attempt+1}] {e}')
            time.sleep(2)
    raise last_err


# 重点区域坐标: (名称, lng, lat)
KEY_AREAS = [
    ('杭州下沙大学城', 120.1189, 30.1343),
    ('杭州未来科技城', 120.0100, 30.2800),
    ('杭州滨江', 120.2130, 30.2100),
    ('宁波南部商务区', 121.5390, 29.8000),
]

# 周边搜索关键词（与品类画像对应）
AROUND_KEYWORDS = [
    # 客群
    ('学校', '大学'), ('学校', '学院'), ('学校', '职业技术学院'), ('学校', '中学'),
    ('办公', '写字楼'), ('办公', '商务大厦'), ('办公', '产业园'),
    ('商圈', '购物中心'), ('商圈', '商场'), ('商圈', '商业街'),
    ('社区', '小区'), ('社区', '公寓'), ('社区', '住宅区'),
    ('通勤', '地铁站'), ('通勤', '公交站'),
    # 竞品
    ('奶茶', '奶茶'), ('甜品', '甜品'), ('早餐', '早餐'), ('便利店', '便利店'),
]


def fetch_around(area_name, lng, lat):
    """对重点区域周边搜索抓取"""
    total_inserted = 0
    for category, kw in AROUND_KEYWORDS:
        rows = []
        page = 1
        while page <= 3:  # 周边搜索每页25, 最多75条足够覆盖
            params = {
                'location': f'{lng},{lat}',
                'keywords': kw,
                'radius': '1500',
                'offset': '25',
                'page': str(page),
                'extensions': 'all',
            }
            try:
                data = http_get(amap_url('/v3/place/around', params))
            except Exception as e:
                print(f'  [skip] {area_name}/{kw}: {e}')
                break
            if data.get('status') != '1':
                print(f'  [warn] {area_name}/{kw}: {data.get("info")}')
                break
            pois = data.get('pois') or []
            if not pois:
                break
            for p in pois:
                loc = p.get('location', '').split(',')
                if len(loc) != 2:
                    continue
                addr = p.get('address', '')
                if isinstance(addr, (list, tuple)):
                    addr = ';'.join(str(x) for x in addr)
                rows.append({
                    'city': p.get('cityname') or area_name[:2],
                    'adname': p.get('adname', ''),
                    'category': category,
                    'poi_type': str(p.get('type', '')),
                    'name': str(p.get('name', '')),
                    'address': str(addr),
                    'lng': float(loc[0]),
                    'lat': float(loc[1]),
                })
            page += 1
            time.sleep(0.3)
        if rows:
            insert_pois(rows)
            total_inserted += len(rows)
        print(f'[{area_name}] {category}/{kw}: 入库 {len(rows)}')
    print(f'== {area_name} 完成, 共入库 {total_inserted} ==\n')


def main():
    for name, lng, lat in KEY_AREAS:
        fetch_around(name, lng, lat)


if __name__ == '__main__':
    main()
