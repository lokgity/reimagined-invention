# -*- coding: utf-8 -*-
"""
fetch_poi.py —— 高德开放平台 POI 预抓取脚本
============================================
- 按浙江省 11 地级市 + 区县网格 + 品类关键词 抓取 POI
- 落本地 SQLite（zj_poi.db），演示时离线使用
- 需在项目根目录 .env 中配置 AMAP_KEY

高德 Web 服务 API:
- POI 搜索: GET https://restapi.amap.com/v3/place/text
    params: key, keywords, city, citylimit=true, offset, page, extensions=all
- 周边搜索: GET https://restapi.amap.com/v3/place/around
    params: key, location(lng,lat), keywords, radius, offset, page

使用注意:
- 免费 key 每日配额有限，抓取务必限速（sleep）
- 个人开发者 key: 去 https://lbs.amap.com 注册 -> 控制台创建应用 -> 拿 Web 服务 key
"""
import sys
import time
import json
import hashlib
import urllib.parse
import urllib.request
import ssl
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import AMAP_KEY, AMAP_SECRET, CATEGORY_PROFILES, TARGET_POI_TYPES, ZHEJIANG_CITIES, DB_PATH  # noqa: E402
from data.query import insert_pois, get_conn  # noqa: E402

AMAP_BASE = 'https://restapi.amap.com/v3/place/text'
CTX = ssl.create_default_context()
SLEEP_SECONDS = 0.3   # 限速：免费配额下不要太激进
PAGE_SIZE = 25        # 高德 text 搜索单页上限 25

# 进程内高德 API 调用计数（成功发起并收到响应的请求数，用于监控配额消耗）
API_CALL_COUNT = 0


def get_api_call_count() -> int:
    """返回当前进程累计发起的高德 API 调用次数"""
    return API_CALL_COUNT


def reset_api_call_count() -> None:
    global API_CALL_COUNT
    API_CALL_COUNT = 0


def amap_sign(params: dict) -> str:
    """高德新版 key 签名：参数按 key 字典序排序拼成 k=v&... 串，末尾拼安全密钥，SHA256 大写"""
    if not AMAP_SECRET:
        return ''
    ordered = '&'.join(f'{k}={params[k]}' for k in sorted(params))
    raw = ordered + AMAP_SECRET
    return hashlib.sha256(raw.encode('utf-8')).hexdigest().upper()


def amap_url(path: str, params: dict) -> str:
    """构造带签名的高德 API URL"""
    p = dict(params)
    p['key'] = AMAP_KEY
    sig = amap_sign(p)
    if sig:
        p['sig'] = sig
    return f'https://restapi.amap.com{path}?{urllib.parse.urlencode(p)}'


def http_get(url, timeout=15, retries=4):
    """带重试的 GET；TLS 握手超时/网络抖动自动重连。
    成功收到响应即计入 API_CALL_COUNT（用于监控配额）。"""
    global API_CALL_COUNT
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                data = json.loads(r.read().decode('utf-8'))
                API_CALL_COUNT += 1
                return data
        except Exception as e:
            last_err = e
            print(f'    [retry {attempt + 1}/{retries}] {type(e).__name__}: {e}')
            time.sleep(2 * (attempt + 1))
    raise last_err


def search_poi(keyword, city, max_pages=40):
    """按关键词+城市搜索 POI，返回 (rows, total)。rows: list[dict]"""
    rows, page, total = [], 1, 0
    while page <= max_pages:
        params = {
            'keywords': keyword, 'city': city,
            'citylimit': 'true', 'offset': PAGE_SIZE, 'page': page,
            'extensions': 'all',
        }
        data = http_get(amap_url('/v3/place/text', params))
        if data.get('status') != '1':
            print(f'  [warn] {city}/{keyword} page{page}: {data.get("info")}')
            break
        pois = data.get('pois') or []
        for p in pois:
            loc = p.get('location', '').split(',')
            if len(loc) != 2:
                continue
            addr = p.get('address', '')
            if isinstance(addr, (list, tuple)):
                addr = ';'.join(str(x) for x in addr)
            rows.append({
                'city': p.get('cityname') or city,
                'adname': p.get('adname', ''),
                'category': None,  # 由调用方设置
                'poi_type': str(p.get('type', '')),
                'name': str(p.get('name', '')),
                'address': str(addr),
                'lng': float(loc[0]),
                'lat': float(loc[1]),
            })
        total = int(data.get('count', 0))
        # 高德限制: 单关键词最多返回约 1000 条(40页); count 超 500 时显示 0
        # 策略: 本页有数据就继续翻页, 直到无数据或达 max_pages 上限
        if not pois:
            break
        if total and page * PAGE_SIZE >= total:
            break
        page += 1
        time.sleep(SLEEP_SECONDS)
    return rows, total


def fetch_all(categories=None, only_target=False):
    """抓取 POI 落库。
    categories: 指定要抓的竞品品类列表（默认全部 4 个）
    only_target: True 时只抓目标客群配套 POI，不抓竞品
    """
    if not AMAP_KEY:
        print('❌ 未配置 AMAP_KEY！请先在高德开放平台注册并创建 Web 服务 key，'
              '写入项目根目录 .env 文件（AMAP_KEY=你的key）')
        return
    total_inserted = 0
    # 1) 竞品 POI（4 品类）
    if not only_target:
        cats = categories or list(CATEGORY_PROFILES.keys())
        for cat in cats:
            prof = CATEGORY_PROFILES[cat]
            for city in ZHEJIANG_CITIES:
                for kw in prof['poi_keywords']:
                    try:
                        rows, total = search_poi(kw, city)
                    except Exception as e:
                        print(f'[跳过] {cat}/{city}/{kw}: {e}')
                        continue
                    for r in rows:
                        r['category'] = cat
                    if rows:
                        insert_pois(rows)
                        total_inserted += len(rows)
                    print(f'[竞品] {cat}/{city}/{kw}: 抓到 {len(rows)}/{total}')
                    time.sleep(SLEEP_SECONDS)
    # 2) 目标客群配套 POI（学校/办公/商圈/社区/通勤）
    for label, kws in TARGET_POI_TYPES.items():
        for city in ZHEJIANG_CITIES:
            for kw in kws:
                try:
                    rows, total = search_poi(kw, city)
                except Exception as e:
                    print(f'[跳过] {label}/{city}/{kw}: {e}')
                    continue
                for r in rows:
                    r['category'] = label  # 配套类直接以 label 命名（学校/办公/商圈/社区/通勤）
                if rows:
                    insert_pois(rows)
                    total_inserted += len(rows)
                print(f'[配套] {label}/{city}/{kw}: 抓到 {len(rows)}/{total}')
                time.sleep(SLEEP_SECONDS)
    print(f'\n完成！共入库 {total_inserted} 条 POI -> {DB_PATH}')


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='抓取高德 POI 数据')
    ap.add_argument('--categories', nargs='*', default=None,
                    help='只抓指定竞品品类，如 --categories 便利店')
    ap.add_argument('--only-target', action='store_true',
                    help='只抓目标客群配套 POI')
    args = ap.parse_args()
    fetch_all(categories=args.categories, only_target=args.only_target)
