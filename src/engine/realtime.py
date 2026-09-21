# -*- coding: utf-8 -*-
"""
realtime.py —— 实时周边搜索（解决预抓取数据覆盖不全的问题）
==============================================================
核心思想: 评分时不只查本地预抓取库, 而是优先实时调用高德"周边搜索"
API (place/around), 获取候选地址周边真实的 POI。这样:
- 评委/用户输入任意地址(哪怕是冷门地点), 都能拿到该点周边真实数据
- 冷门地点不再因为"预抓取没覆盖"而评分失真

成本: 每个地址分析 ≈ 6 次 API 调用(竞品1 + 配套5类), 月配额5000次
      ≈ 可分析 800+ 个地址, 足够演示使用
兜底: API 调用失败(配额/网络)时, 自动回落到本地预抓取库
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CATEGORY_PROFILES, TARGET_POI_TYPES  # noqa: E402
from data.fetch_poi import amap_url, http_get  # noqa: E402
from data.query import query_within  # noqa: E402

# 进程内缓存: (category, round(lng,4), round(lat,4)) -> [(name, lng, lat, poi_type, adname, distance)]
_CACHE = {}
# 是否启用实时模式（默认启用；可设 REALTIME=0 关闭）
REALTIME_ENABLED = True


def set_realtime(enabled: bool):
    global REALTIME_ENABLED
    REALTIME_ENABLED = enabled


def init_from_env():
    """从环境变量 REALTIME 初始化（REALTIME=0 关闭实时模式）"""
    import os
    global REALTIME_ENABLED
    if os.getenv('REALTIME') == '0':
        REALTIME_ENABLED = False


init_from_env()


# 各配套类的周边搜索关键词（复用 TARGET_POI_TYPES）
# 竞品类关键词直接从品类画像取
def _search_around(keyword, lng, lat, radius, max_pages=1):
    """调用高德周边搜索, 返回 [(name, lng, lat, poi_type, adname, distance)]
    max_pages 默认 1（省配额）：25 条对 Huff 引力足够，不再翻页。"""
    results = []
    page = 1
    while page <= max_pages:
        params = {
            'location': f'{lng},{lat}',
            'keywords': keyword,
            'radius': str(radius),
            'offset': '25',
            'page': str(page),
            'extensions': 'all',
        }
        try:
            # ⚠️ retries=2 必须显式传（2026-09-16 修）。
            #  http_get 默认 retries=4，退避是 2+4+6+8=20s；而本函数在**评分主路径**上，
            #  每次地址分析要按 5 个配套类目各调一次 → 最坏 4×10s 超时 + 20s 睡眠 ≈ 60s
            #  的病理路径。同项目 competitor_insight.py:211 早已把它收敛到 2 并写明理由
            #  （"退避 2+4+6+8=20s，评分路径上太久"），realtime 这条路上漏了。
            data = http_get(amap_url('/v3/place/around', params), timeout=10, retries=2)
        except Exception:
            break  # 网络失败, 返回已抓到的
        if data.get('status') != '1':
            break  # 配额超限等
        pois = data.get('pois') or []
        if not pois:
            break
        for p in pois:
            loc = p.get('location', '').split(',')
            if len(loc) != 2:
                continue
            results.append({
                'name': str(p.get('name', '')),
                'lng': float(loc[0]),
                'lat': float(loc[1]),
                'poi_type': str(p.get('type', '')),
                'adname': str(p.get('adname', '')),
                'distance': 0,  # 距离由调用方按需计算
            })
        page += 1
        time.sleep(0.15)
    return results


def get_surrounding(category, lng, lat, radius):
    """获取候选地址周边指定类别的 POI。
    优先级: 本地预抓取库(0 次 API) > 实时兜底(本地无数据时, 1 个代表词 × 1 页)。
    category 取值: 奶茶/甜品/早餐/便利店(竞品) 或 学校/办公/商圈/社区/通勤(配套)
    """
    key = (category, round(lng, 4), round(lat, 4))
    if key in _CACHE:
        return _CACHE[key]

    # 1) 本地预抓取库优先：0 次 API 调用、响应快、演示稳定
    local = query_within(category, lng, lat, radius)
    if local:
        _CACHE[key] = local
        return local

    # 2) 本地无数据才实时兜底（省高德配额）：
    #    每个类别只搜 1 个代表词 × 1 页，控制在 ~5 次调用/地址
    result = None
    if REALTIME_ENABLED:
        if category in CATEGORY_PROFILES:
            kws = CATEGORY_PROFILES[category]['poi_keywords'][:1]
        elif category in TARGET_POI_TYPES:
            kws = TARGET_POI_TYPES[category][:1]
        else:
            kws = [category]
        merged = {}
        for kw in kws:
            pois = _search_around(kw, lng, lat, radius, max_pages=1)
            for p in pois:
                k = (p['name'], round(p['lng'], 4), round(p['lat'], 4))
                if k not in merged:
                    merged[k] = p
        if merged:
            result = list(merged.values())

    if result is None:
        result = []

    _CACHE[key] = result
    return result


def clear_cache():
    _CACHE.clear()
