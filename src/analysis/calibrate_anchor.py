# -*- coding: utf-8 -*-
"""
calibrate_anchor.py —— 标定引擎流水模型的锚点常量 REF_DP
============================================================
引擎新流水公式: 日单量 = 基准日单量 × (D×P)/REF_DP × 面积×城市×保守系数
  D = 0.8×(学校+办公+社区POI数) + 0.2×(商圈POI数)   [本地库, 500m]
  P = 真 Huff 捕获份额(λ=2.0, d0=50m, 品牌S)
REF_DP = 83 家真实门店 D×P 的中位数 —— 含义:
  "一家典型门店(中位水平)的日单量 = 品类基准日单量"
本脚本用【引擎运行时完全相同】的查询路径(query_within 本地库)计算,
保证锚点与线上行为一致。
"""
import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from config import get_profile  # noqa: E402
from data.query import query_within  # noqa: E402
from engine.scoring import query_pois, dist_report  # noqa: E402
from engine.brands import brand_attractiveness, BRAND_S  # noqa: E402

LAMBDA, D0, RADIUS = 2.0, 50.0, 500


def engine_demand(lng, lat, radius=RADIUS):
    """与引擎 estimate_demand 完全相同的定义。

    ⚠️ 距离口径必须走 `scoring.query_pois`（**步行路网距离**），
       不能再直接用 `data.query.query_within`（直线）。
       2026-09-20 换路网口径时正是这里踩到：本脚本原先自己复制了一份定义、
       直接调 query_within，改口径时它**不会跟随**，锚点就会按旧口径标错。
       ⇒ 下面 main() 里有一步「与引擎对拍」的护栏，防止再次漂移。
    """
    n_a = (len(query_pois('学校', lng, lat, radius))
           + len(query_pois('办公', lng, lat, radius))
           + len(query_pois('社区', lng, lat, radius)))
    n_b = len(query_pois('商圈', lng, lat, radius))
    return 0.8 * n_a + 0.2 * n_b


def capture_share(lng, lat, own_S, radius=RADIUS, lam=LAMBDA, d0=D0):
    """与引擎 capture_share 完全相同的定义（竞争集合=本地库奶茶POI）"""
    own = own_S / (d0 ** lam)
    comp = 0.0
    for p in query_pois('奶茶', lng, lat, radius):   # 步行路网口径
        if abs(p['lng'] - lng) < 1e-6 and abs(p['lat'] - lat) < 1e-6:
            continue  # 自己
        _, s_k = brand_attractiveness(p['name'])
        comp += s_k / ((p['distance'] + d0) ** lam)
    return own / (own + comp) if (own + comp) > 0 else 1.0


def resolve_own_S(row):
    """解析门店自身的品牌引力 S —— 与引擎运行时**同口径**。

    修复记录（2026-09-15）:
      旧实现 `own_S = float(r['吸引力系数']) if r['吸引力系数'] else 1.0`
      而 stores_calib.csv 的「吸引力系数」列 83 行中仅 1 行非空，
      导致 82 家门店的 own_S 全部退化为 1.0（品牌盲标定）。
      但运行时 score_竞争压力 传的是 BRAND_S[brand]（带品牌），
      分子带品牌、分母不带 → P 被系统性抬高，锚点失真。

    新实现按**引擎同样的顺序**解析:
      1) 若「吸引力系数」列有值 → 用它（人工覆写优先）
      2) 否则用店名过 brand_attractiveness（与 scoring.capture_share
         识别竞品时用的是同一个函数）
      3) 否则用「品牌」列查 BRAND_S
      4) 全失败 → 1.0（个体杂牌）
    """
    raw = (row.get('吸引力系数') or '').strip()
    if raw:
        try:
            return float(raw), 'column'
        except ValueError:
            pass
    brand, s = brand_attractiveness(row.get('名称') or '')
    if brand:
        return s, f'name:{brand}'
    b = (row.get('品牌') or '').strip()
    if b in BRAND_S:
        return BRAND_S[b], f'brand_col:{b}'
    return 1.0, 'default'


def main():
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass

    rows = []
    with open(HERE / 'stores_calib.csv', encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            rows.append(r)
    print(f'样本 {len(rows)} 家')

    # ---- 护栏①：与引擎对拍（防"自己复制一份定义"再次漂移）----
    _r0 = rows[0]
    _lng0, _lat0 = float(_r0['经度']), float(_r0['纬度'])
    from engine import scoring as _S
    _d_script = engine_demand(_lng0, _lat0)
    _d_engine = _S.estimate_demand(_lng0, _lat0, RADIUS)
    print(f'  [护栏①] 与引擎对拍 D: 本脚本={_d_script:.1f} 引擎={_d_engine:.1f} '
          f'{"一致 ✓" if abs(_d_script - _d_engine) < 1e-9 else "★不一致 ✗"}')
    assert abs(_d_script - _d_engine) < 1e-9, '本脚本的 D 定义与引擎漂移了，先修脚本再标定'

    dps, details, dps_blind = [], [], []
    src_stat = {}
    for r in rows:
        lng, lat = float(r['经度']), float(r['纬度'])
        own_S, src = resolve_own_S(r)
        src_stat[src] = src_stat.get(src, 0) + 1
        d = engine_demand(lng, lat)
        p = capture_share(lng, lat, own_S)
        p_blind = capture_share(lng, lat, 1.0)
        dp = d * p
        dps.append(dp)
        dps_blind.append(d * p_blind)
        details.append((r['名称'], r['商圈'], own_S, round(d, 1),
                        round(p, 4), round(dp, 2), round(p_blind, 4)))

    # ---- 护栏②：混口径的锚点没有意义，回退占比 > 0 就拒绝出数 ----
    _dr = dist_report()
    print(f'  [护栏②] 距离口径：{_dr["口径"]}')
    print(f'           步行 {_dr["步行"]} 点 / 直线回退 {_dr["直线回退"]} 点'
          f'（回退占比 {_dr["直线回退占比"]:.2%}）')
    if _dr['直线回退']:
        raise SystemExit('★ 有 %d 个点回退到直线口径 —— 混口径标定出来的锚点不可用。'
                         '先把路网距离抓全（重跑本脚本即可断点续传），再标定。'
                         % _dr['直线回退'])

    dps_sorted = sorted(dps)
    n = len(dps_sorted)
    median = dps_sorted[n // 2] if n % 2 else (dps_sorted[n // 2 - 1] + dps_sorted[n // 2]) / 2
    mean = sum(dps) / n

    n_bl = len(dps_blind)
    sb = sorted(dps_blind)
    med_blind = sb[n_bl // 2] if n_bl % 2 else (sb[n_bl // 2 - 1] + sb[n_bl // 2]) / 2

    print(f'\n  own_S 来源统计: {src_stat}')
    print(f'\n【品牌一致口径】D×P 分布: min={min(dps):.2f} 中位={median:.2f} '
          f'均值={mean:.2f} max={max(dps):.2f}')
    print(f'【品牌盲（旧口径）】D×P 中位 = {med_blind:.2f}')
    print(f'\n>>> 引擎锚点常量 REF_DP = {median:.2f}   （旧值 4.35）')
    print(f'    放大倍数 = {median / med_blind:.4f}')

    # P_REF：走映射式的门店其捕获份额中位数（剔除 n_comp==0 蓝海特例）
    ps = [p for (_, _, _, _, p, _, _) in details if 0 < p < 1.0]
    ps_sorted = sorted(ps)
    m = len(ps_sorted)
    p_med = ps_sorted[m // 2] if m % 2 else (ps_sorted[m // 2 - 1] + ps_sorted[m // 2]) / 2
    print(f'\n>>> 竞争分锚点 P_REF = {p_med:.4f}   （旧值 0.40，基于 {m} 家非蓝海门店）')

    print('\n样本明细(前15):')
    for name, area, S, d, p, dp, pb in details[:15]:
        print(f'  {area} | {name[:20]:<22} S={S:>3} D={d:>6} '
              f'P={p:>7} P_blind={pb:>7} D×P={dp:>8}')

    with open(HERE / 'anchor_calib.csv', 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['名称', '商圈', 'S', 'D', 'P', 'D×P', 'P_blind'])
        for name, area, S, d, p, dp, pb in details:
            w.writerow([name, area, S, d, p, dp, pb])
        w.writerow([])
        w.writerow(['REF_DP(中位,品牌一致)', median])
        w.writerow(['REF_DP(中位,品牌盲)', med_blind])
        w.writerow(['P_REF(中位,品牌一致)', p_med])
    print('\n已保存 anchor_calib.csv')


if __name__ == '__main__':
    main()
