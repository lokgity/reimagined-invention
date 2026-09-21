# -*- coding: utf-8 -*-
"""
fetch_stores.py —— λ 标定样本抓取：三商圈奶茶店清单
======================================================
对目标商圈调用高德"周边搜索"，抓取奶茶/茶饮门店（名称/经纬度/品牌），
输出 calibrate_lambda.py 所需的 CSV（外卖月售列留空待人工抄录）。

商圈中心通过高德地点搜索自动解析（place/text），不手写坐标。

用法:
  python src/analysis/fetch_stores.py
输出:
  src/analysis/stores_raw.csv
"""
import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data.fetch_poi import amap_url, http_get  # noqa: E402

# ---------------------------------------------------------------
# 目标商圈: (商圈名, 搜索词, 城市, 搜索半径m, 翻页数)
# 县城商圈门店稀疏，半径放大
# ---------------------------------------------------------------
AREAS = [
    ('宁波天一广场', '天一广场', '宁波', 800, 3),
    ('杭州湖滨in77', '湖滨银泰in77', '杭州', 800, 3),
    ('海宁银泰商圈', '海宁银泰城', '嘉兴海宁', 1500, 3),
]

KEYWORDS = '奶茶|茶饮果汁'

# 已知连锁品牌（用于自动识别品牌列；识别不出 → 个体/杂牌）
BRANDS = ['蜜雪冰城', '古茗', '茶百道', '沪上阿姨', '霸王茶姬', '喜茶', '奈雪',
          '一点点', 'CoCo', '都可', '益禾堂', '甜啦啦', '书亦烧仙草', '茉酸奶',
          '7分甜', '乐乐茶', '伏小桃', '百分茶', '新时沏', '加减茶饮', '陈文鼎',
          '煲珠公', '茉莉奶白', '淡马茶坊', '茶话弄', '悸动', '贡茶', '鹿角巷',
          '黑泷堂', '阿水大杯茶', '巡茶', '快乐番薯', '冰淳茶饮', '柠季',
          'LINLEE', '林里', '茶救星球', '雅克雅思', '树夏', '吾饮良品']

# 名称必须命中其一才保留（过滤咖啡店等非目标 POI）
INCLUDE_HINTS = ['茶', '奶', '饮', '果汁', '柠檬', '烧仙草', '酸奶', '冰城',
                 'CoCo', 'LINLEE']
# 明确排除（咖啡/酒吧/食堂等噪音）
EXCLUDE_HINTS = ['咖啡', '酒吧', '食堂', '火锅', '烧烤', '面馆', '汉堡',
                 '炸鸡', '蛋糕', '烘焙', '面包']


def resolve_center(keyword, city):
    """用地点搜索解析商圈中心坐标"""
    params = {'keywords': keyword, 'city': city, 'offset': '5', 'page': '1'}
    data = http_get(amap_url('/v3/place/text', params), timeout=10)
    if data.get('status') != '1' or not data.get('pois'):
        return None
    p = data['pois'][0]
    lng, lat = p['location'].split(',')
    return float(lng), float(lat), p.get('name', '')


def search_milktea(lng, lat, radius, pages):
    """周边搜索奶茶门店，多页合并去重"""
    merged = {}
    for page in range(1, pages + 1):
        params = {'location': f'{lng},{lat}', 'keywords': KEYWORDS,
                  'radius': str(radius), 'offset': '25', 'page': str(page),
                  'extensions': 'all'}
        try:
            data = http_get(amap_url('/v3/place/around', params), timeout=10)
        except Exception as e:
            print(f'  ⚠️ 第{page}页请求失败: {e}')
            break
        if data.get('status') != '1':
            print(f"  ⚠️ API 返回异常: {data.get('info')} ({data.get('infocode')})")
            break
        pois = data.get('pois') or []
        if not pois:
            break
        for p in pois:
            name = str(p.get('name', ''))
            loc = p.get('location', '').split(',')
            if len(loc) != 2:
                continue
            key = (name, round(float(loc[0]), 4), round(float(loc[1]), 4))
            if key not in merged:
                merged[key] = {
                    'name': name,
                    'lng': float(loc[0]),
                    'lat': float(loc[1]),
                    'type': str(p.get('type', '')),
                    'address': str(p.get('address', '')) if isinstance(p.get('address'), str) else '',
                }
        time.sleep(0.3)
    return list(merged.values())


def classify(name):
    """返回 (是否保留, 品牌)"""
    for h in EXCLUDE_HINTS:
        if h in name:
            return False, ''
    if not any(h in name for h in INCLUDE_HINTS):
        return False, ''
    for b in BRANDS:
        if b in name:
            return True, b if b != '都可' else 'CoCo'
    return True, '个体/杂牌'


def main():
    out_path = Path(__file__).resolve().parent / 'stores_raw.csv'
    rows = []
    for area, kw, city, radius, pages in AREAS:
        print(f'\n=== {area}（{kw} @ {city}，半径{radius}m）===')
        center = resolve_center(kw, city)
        if not center:
            print(f'  ❌ 无法解析商圈中心，跳过')
            continue
        clng, clat, cname = center
        print(f'  中心: {cname} ({clng:.5f}, {clat:.5f})')
        pois = search_milktea(clng, clat, radius, pages)
        kept, dropped = 0, 0
        for p in pois:
            ok, brand = classify(p['name'])
            if not ok:
                dropped += 1
                continue
            kept += 1
            rows.append({'商圈': area, '名称': p['name'], '经度': p['lng'],
                         '纬度': p['lat'], '外卖月售': '', '品牌': brand,
                         '吸引力系数': '', '地址': p['address']})
        print(f'  抓到 {len(pois)} 条，保留奶茶店 {kept} 家，过滤噪音 {dropped} 条')

    with open(out_path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['商圈', '名称', '经度', '纬度',
                                          '外卖月售', '品牌', '吸引力系数', '地址'])
        w.writeheader()
        w.writerows(rows)
    print(f'\n===== 合计 {len(rows)} 家，已保存: {out_path} =====')
    print('下一步: 人工抄录"外卖月售"列（美团+饿了么月售之和），'
          '无外卖的店填 无外卖 备注后标定时剔除')


if __name__ == '__main__':
    main()
