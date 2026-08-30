# -*- coding: utf-8 -*-
"""
rental58.py —— 58同城商铺出租数据抓取（Playwright）
====================================================
从 58 同城商铺出租列表页提取结构化数据: 名称/位置/月租/单价/面积。
数据源: https://{city}.58.com/shangpu/  (如 hz.58.com)

注意:
- 58 列表页无需登录即可访问(经实测), 用 Playwright 真实浏览器可绕过基础反爬
- 贝壳/安居客有验证码反爬, 不可用
- 仅供项目演示/研究使用, 遵守 58 同城用户协议, 控制请求频率
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 城市代码映射（58 用拼音短码）
CITY_CODES = {
    '杭州': 'hz', '宁波': 'nb', '温州': 'wz', '嘉兴': 'jx',
    '湖州': 'huz', '绍兴': 'sx', '金华': 'jh', '衢州': 'quzhou',
    '舟山': 'zs', '台州': 'tz', '丽水': 'ls',
}


def _parse_card(text):
    """解析单个 li 卡片的文本, 提取结构化字段"""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    price = price_per = area = None
    title, loc = '', ''
    for l in lines:
        m = re.match(r'([\d.]+)\s*(万|元)/月', l)
        if m and price is None:
            price = float(m.group(1)) * (10000 if m.group(2) == '万' else 1)
            continue
        m2 = re.match(r'([\d.]+)元/㎡/天', l)
        if m2 and price_per is None:
            price_per = float(m2.group(1))
            continue
        m3 = re.match(r'^(\d+)\s*㎡$', l)
        if m3 and area is None:
            a = int(m3.group(1))
            if 5 <= a <= 5000:
                area = a
            continue
    for l in lines:
        if any(k in l for k in ['图', '元/月', '元/㎡', '㎡', '建筑面积']):
            continue
        if len(l) > 8:
            title = l
            break
    for l in lines:
        if '-' in l and len(l) < 40 and '地铁' not in l:
            loc = l
            break
    if price is None:
        return None
    return {
        'title': title, 'loc': loc,
        'price': price, 'price_per': price_per, 'area': area,
    }


def fetch_shops(city, limit=10, timeout=25, area_filter=None):
    """抓取指定城市的 58 商铺出租列表, 返回结构化条目列表。
    area_filter: 区域/街道关键词(如"滨江""下沙"), 只保留 loc 字段匹配的条目。
    若 Playwright 不可用或抓取失败, 返回空列表(调用方回落到高德POI)。"""
    code = CITY_CODES.get(city, city)
    url = f'https://{code}.58.com/shangpu/'
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return []
    items = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1400, 'height': 900})
            page.goto(url, wait_until='domcontentloaded', timeout=timeout * 1000)
            page.wait_for_timeout(4000)
            lis = page.locator('li')
            for i in range(lis.count()):
                try:
                    t = lis.nth(i).inner_text()
                except Exception:
                    continue
                if '元/月' not in t or '㎡' not in t:
                    continue
                item = _parse_card(t)
                if not item:
                    continue
                # 区域过滤: loc(如"滨江-四桥南") 或 title 需包含区域词
                if area_filter:
                    full = (item['loc'] + item['title'])
                    # 去掉城市名再匹配(区域词如"滨江"不含"杭州")
                    if area_filter not in full and area_filter not in item['loc']:
                        continue
                items.append(item)
                if len(items) >= limit:
                    break
            browser.close()
    except Exception:
        pass
    return items


if __name__ == '__main__':
    shops = fetch_shops('杭州', limit=10)
    print(f'抓到 {len(shops)} 条:')
    for s in shops:
        print(f"  [{s['loc']}] {s['title'][:25]} | {s['price']:.0f}元/月 | {s['area']}㎡")
