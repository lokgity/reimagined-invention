# -*- coding: utf-8 -*-
"""
check_anchor_consistency.py —— 锚点口径一致性核查
==================================================
背景：scoring.py 的两个锚点常量 REF_DP=4.35 / P_REF=0.40 是 83 家真实门店
D×P 与 P 的中位数，但 calibrate_anchor.py:63 读的是 stores_calib.csv 的
「吸引力系数」列——该列整列为空，于是 own_S 全部退化为 1.0。
也就是说【锚点是品牌盲的】，而运行时 score_竞争压力 / estimate_monthly_sales
传入的 own_S = BRAND_S[brand] 是【带品牌的】。分子带品牌、分母不带，
比值被系统性抬高。

本脚本在纯本地库模式（REALTIME=0，零 API）下，对同一批地址分别用
「现锚点」与「品牌一致锚点」跑完整 score_site，量化偏差。
不修改任何生产代码，只在本进程内覆盖常量。
"""
import os
import sys
from pathlib import Path

os.environ['REALTIME'] = '0'          # 必须在 import 前设置

HERE = Path(__file__).resolve().parent
SRC = HERE.parent.parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(HERE.parent))

import pandas as pd                                        # noqa: E402
from engine import scoring                                 # noqa: E402
from calibrate_anchor import engine_demand, capture_share   # noqa: E402
from engine.brands import BRAND_S                           # noqa: E402

# 客单价参照：注入固定值，避免 score_site 自己发高德 API
PRICE_REF = {
    '校正客单价': 7.0, '品类画像客单价': 16, '校正倍数': 16 / 7,
    '口径': '已用同品牌 2 家门店的高德真实人均 ¥7 覆盖品类画像假设 ¥16',
    '证据': {'样本数': 2, '同品牌人均中位': 7.0,
             '门店': ['蜜雪冰城(天一广场店)', '蜜雪冰城(东鼓道店)']},
}


def recalibrate():
    """用品牌一致的 P 重算两个锚点（83 家，纯本地库）。"""
    st = pd.read_csv(HERE.parent / 'stores_calib.csv', encoding='utf-8-sig')
    dp_brand, dp_blind, p_brand, p_blind = [], [], [], []
    for _, r in st.iterrows():
        S = BRAND_S.get(r['品牌'], 1.0)
        d = engine_demand(r['经度'], r['纬度'])
        pb = capture_share(r['经度'], r['纬度'], 1.0)
        pS = capture_share(r['经度'], r['纬度'], S)
        dp_blind.append(d * pb); dp_brand.append(d * pS)
        p_blind.append(pb); p_brand.append(pS)
    return {
        'REF_DP_blind': float(pd.Series(dp_blind).median()),
        'REF_DP_brand': float(pd.Series(dp_brand).median()),
        'P_REF_blind': float(pd.Series(p_blind).median()),
        'P_REF_brand': float(pd.Series(p_brand).median()),
    }


def run_case(brand, lng, lat, rent, area, invest, staff):
    return scoring.score_site('奶茶', lng, lat, rent, name='核查案例', area_m2=area,
                              city='宁波', investment=invest, staff=staff,
                              brand=brand, price_ref=PRICE_REF)


def main():
    anc = recalibrate()
    print('=== 锚点重标定（83 家，纯本地库，零 API）===')
    for k, v in anc.items():
        print(f'  {k:<14} {v:.4f}')
    print(f'\n  现用 REF_DP {scoring.REF_DP["奶茶"]}  vs 品牌盲重算 {anc["REF_DP_blind"]:.4f}'
          f'  → 吻合' if abs(scoring.REF_DP['奶茶'] - anc['REF_DP_blind']) < 0.02 else '  → 不吻合')
    print(f'  现用 P_REF  {scoring.P_REF["奶茶"]}  vs 品牌盲重算 {anc["P_REF_blind"]:.4f}'
          f'  → 吻合' if abs(scoring.P_REF['奶茶'] - anc['P_REF_blind']) < 0.02 else '  → 不吻合')
    print(f'\n  流水放大倍数 = REF_DP_brand / REF_DP_blind = '
          f'{anc["REF_DP_brand"] / anc["REF_DP_blind"]:.4f}')
    print(f'  竞争分放大倍数 = P_REF_brand / P_REF_blind = '
          f'{anc["P_REF_brand"] / anc["P_REF_blind"]:.4f}')

    cases = [
        ('蜜雪冰城', 121.556573, 29.869959, '天一广场(头部demo)'),
        ('奈雪', 121.554918, 29.869261, '天一广场 奈雪'),
        ('个体/杂牌', 120.16331, 30.252845, 'in77 个体户(S=1)'),
    ]
    for label, ref_dp, p_ref in [('现锚点(品牌盲)', anc['REF_DP_blind'], anc['P_REF_blind']),
                                 ('一致锚点(带品牌)', anc['REF_DP_brand'], anc['P_REF_brand'])]:
        scoring.REF_DP['奶茶'] = round(ref_dp, 4)
        scoring.P_REF['奶茶'] = round(p_ref, 4)
        print(f'\n=== {label}: REF_DP={ref_dp:.4f}  P_REF={p_ref:.4f} ===')
        for brand, lng, lat, note in cases:
            r = run_case(brand if brand != '个体/杂牌' else None, lng, lat, 12000, 30, 200000, 2)
            e = r['evidence']
            pr = r.get('profit') or {}
            rl = r.get('rent_limits') or {}
            print(f'  [{note}] S={r["own_brand_S"]}  P={e["捕获份额P"]:.4f}'
                  f'  日单量={e["预估日单量"]}  月流水={e["预估月流水"]:,}')
            print(f'      竞争压力={r["dims"].get("竞争压力")}  总分={r["total"]}'
                  f'  月净利={pr.get("月净利估算")}'
                  f'  盈亏平衡={rl.get("盈亏平衡月租")}  回本上限={rl.get("回本达标月租上限")}'
                  f'  否决={r["veto"].get("触发")}  {r["verdict"]}')

    scoring.REF_DP['奶茶'] = 4.35
    scoring.P_REF['奶茶'] = 0.40


if __name__ == '__main__':
    main()
