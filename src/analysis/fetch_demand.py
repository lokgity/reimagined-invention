# -*- coding: utf-8 -*-
"""
fetch_demand.py —— 抓取各门店周边需求 POI 规模（Huff 模型的需求项 D）
======================================================================
对每家门店调用高德周边搜索（offset=1，只取 count 总数，不拉明细），
两组关键词:
  A 客群(权重0.8): 学校/写字楼/产业园/小区/公寓
  B 商业(权重0.2): 购物中心/商场/商业街/步行街
D = 0.8 * countA + 0.2 * countB

特性: 结果增量写入 demand.csv，中断后重跑自动续传（应对每日配额限制）。
用法: python src/analysis/fetch_demand.py
"""
import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data.fetch_poi import amap_url, http_get  # noqa: E402

HERE = Path(__file__).resolve().parent
KW_A = '大学|学院|写字楼|商务大厦|产业园|小区|公寓'
KW_B = '购物中心|商场|商业街|步行街'
W_A, W_B = 0.8, 0.2
RADIUS = 500


def get_count(lng, lat, keywords):
    params = {'location': f'{lng},{lat}', 'keywords': keywords,
              'radius': str(RADIUS), 'offset': '1', 'page': '1'}
    data = http_get(amap_url('/v3/place/around', params), timeout=10)
    if data.get('status') != '1':
        raise RuntimeError(f"API 错误: {data.get('info')} ({data.get('infocode')})")
    return int(data.get('count') or 0)


def main():
    stores = list(csv.DictReader(open(HERE / 'stores_calib.csv', encoding='utf-8-sig')))
    done = {}
    out_path = HERE / 'demand.csv'
    if out_path.exists():
        for r in csv.DictReader(open(out_path, encoding='utf-8-sig')):
            done[r['名称']] = r
        print(f'续传: 已完成 {len(done)} 家')

    f = open(out_path, 'a', encoding='utf-8-sig', newline='')
    w = csv.writer(f)
    if not done:
        w.writerow(['名称', '客群POI数', '商业POI数', '需求D'])

    n_ok = 0
    try:
        for i, s in enumerate(stores, 1):
            name = s['名称']
            if name in done:
                continue
            try:
                ca = get_count(s['经度'], s['纬度'], KW_A)
                time.sleep(0.35)
                cb = get_count(s['经度'], s['纬度'], KW_B)
            except RuntimeError as e:
                print(f'\n❌ 第{i}家 {name} 失败: {e}')
                print('已保存进度。若是配额超限(个人key 100次/日)，明天重跑本脚本即可续传。')
                break
            d = W_A * ca + W_B * cb
            w.writerow([name, ca, cb, round(d, 1)])
            f.flush()
            n_ok += 1
            print(f'[{i}/{len(stores)}] {name}: 客群{ca} 商业{cb} D={d:.0f}')
            time.sleep(0.35)
    finally:
        f.close()
    print(f'\n本次新增 {n_ok} 家，累计 {len(done) + n_ok}/{len(stores)}')


if __name__ == '__main__':
    main()
