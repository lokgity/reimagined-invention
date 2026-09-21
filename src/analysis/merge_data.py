# -*- coding: utf-8 -*-
"""
merge_data.py —— 合并人工录入的外卖月售与门店坐标，生成标定输入
================================================================
输入:
  stores_raw.csv            (fetch_stores.py 抓的坐标母表, utf-8-sig)
  rpa_input_*.csv           (人工录入月售, 可能是 utf-8 或 gbk)
输出:
  stores_calib.csv          (全部样本: 名称,经度,纬度,外卖月售,品牌,商圈)
  stores_calib_<商圈>.csv   (分商圈样本)
  brands.csv                (品牌引力系数表, 按全国门店数量级分档)
剔除规则:
  - 美团/饿了么月售均为 0 (装修/停业) → 剔除并打印
"""
import csv
import io
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# 品牌引力系数 S（按全国门店数量级 + 品牌势能分档，窄门餐眼 2026 口径参考）
BRAND_S = {
    '蜜雪冰城': 2.5,   # 3万+ 家，绝对头部
    '古茗': 2.2,       # 万店级，浙江本土强势
    '霸王茶姬': 2.0,   # 高势能新中式
    '喜茶': 2.0,       # 高端头部
    '爷爷不泡茶': 2.0, # 数千家，新中式头部
    '沪上阿姨': 1.8,   # 万店级
    'CoCo': 1.8,       # 老牌万店级
    '奈雪': 1.8,
    '茶百道': 1.8,
    '茉酸奶': 1.6,
    '乐乐茶': 1.6,
    '周四晚': 1.6,     # 杭州高势能连锁
    '茶理宜世': 1.5,   # 数百家连锁
    'LINLEE': 1.5,
    '茉莉奶白': 1.5,
    '裕莲茶楼': 1.5,   # 杭州本地强连锁
    '煲珠公': 1.4,
    '春莱': 1.4,       # 泰式奶茶连锁
    '李若桃': 1.4,     # 手作酸奶连锁
    '麦记牛奶': 1.4,   # 连锁
    'OT另茶': 1.4,
    '一点点': 1.6,
    '麒麟大口茶': 1.3,
    'VQ鲜榨果汁': 1.3,
    '宝圆圆': 1.3,
    '就是柠': 1.3,
    'Tamkoko泰柯茶园': 1.2,
    'angtea艾熟茶': 1.2,
    '柠好鸭': 1.2,
    '闲吉': 1.1,
    '个体/杂牌': 1.0,
}

# 按店名识别连锁品牌（修复抓取时被误判为"个体/杂牌"的连锁）
NAME_BRAND = {
    '爷爷不泡茶': '爷爷不泡茶', 'NOYEYENOTEA': '爷爷不泡茶',
    '周四晚': '周四晚', '裕莲茶楼': '裕莲茶楼', '春莱': '春莱',
    '李若桃': '李若桃', '麦记牛奶': '麦记牛奶', '茶理宜世': '茶理宜世',
    '另茶': 'OT另茶', '麒麟大口茶': '麒麟大口茶', 'VQ': 'VQ鲜榨果汁',
    '宝圆圆': '宝圆圆', '就是柠': '就是柠', '泰柯': 'Tamkoko泰柯茶园',
    '艾熟茶': 'angtea艾熟茶', '柠好鸭': '柠好鸭', '闲吉': '闲吉',
}


def read_rows(path):
    raw = path.read_bytes()
    for enc in ('utf-8-sig', 'gbk'):
        try:
            return list(csv.DictReader(io.StringIO(raw.decode(enc))))
        except UnicodeDecodeError:
            continue
    raise ValueError(f'无法识别编码: {path}')


def main():
    # 坐标母表: 名称 -> (lng, lat)
    master = {}
    for r in read_rows(HERE / 'stores_raw.csv'):
        master[r['名称']] = (r['经度'], r['纬度'], r['品牌'], r['商圈'])

    merged, excluded, missing_coord = [], [], []
    for fn in sorted(HERE.glob('rpa_input_*.csv')):
        for r in read_rows(fn):
            name = r['搜索关键词'].strip()
            mt = (r.get('美团月售') or '').strip()
            elm = (r.get('饿了么月售') or '').strip()
            try:
                total = int(float(mt or 0)) + int(float(elm or 0))
            except ValueError:
                excluded.append((name, f'月售无法解析: {mt}/{elm}'))
                continue
            if total == 0:
                excluded.append((name, '双平台月售为0(装修/停业)'))
                continue
            if name not in master:
                missing_coord.append(name)
                continue
            lng, lat, brand, area = master[name]
            if brand == '个体/杂牌':
                for kw, b in NAME_BRAND.items():
                    if kw in name:
                        brand = b
                        break
            merged.append({'商圈': area, '名称': name, '经度': lng, '纬度': lat,
                           '外卖月售': total, '品牌': brand, '吸引力系数': ''})

    fields = ['名称', '经度', '纬度', '外卖月售', '品牌', '吸引力系数', '商圈']
    with open(HERE / 'stores_calib.csv', 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(merged)

    areas = {}
    for m in merged:
        areas.setdefault(m['商圈'], []).append(m)
    for area, items in areas.items():
        with open(HERE / f'stores_calib_{area}.csv', 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(items)

    with open(HERE / 'brands.csv', 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['品牌', '系数'])
        for b, s in BRAND_S.items():
            w.writerow([b, s])

    print(f'合并完成: 有效样本 {len(merged)} 家')
    for area, items in areas.items():
        print(f'  {area}: {len(items)} 家')
    if excluded:
        print(f'剔除 {len(excluded)} 家:')
        for n, why in excluded:
            print(f'  - {n} ({why})')
    if missing_coord:
        print(f'⚠️ {len(missing_coord)} 家在母表中找不到坐标(名称不一致):')
        for n in missing_coord:
            print(f'  - {n}')
    print('输出: stores_calib.csv / stores_calib_<商圈>.csv / brands.csv')


if __name__ == '__main__':
    main()
