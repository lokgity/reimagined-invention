# -*- coding: utf-8 -*-
"""verify_analysis_metrics.py —— 判别指标（AUC）+ 结论翻转率的**离线门禁**
================================================================================
2026-09-28 新增。覆盖两条专家评审 P1：
  ① 回测从「描述性对照」升级为「判别指标（AUC）」
  ② 「排序相关 0.921 ≠ 结论稳」—— 补「结论翻转率」

这两个模块是**纯统计**（无网络、无外部数据），所以必须进离线门禁：
统计口径算错最容易"看起来合理"，且不会有任何别的测试挡住它。

钉的不变式：
  §1 AUC 的定义与边界（完全可分=1 / 完全反向=0 / 同分布=0.5 / 平局=0.5）
  §2 AUC 抗离群（只用排序）—— 这是它相对均值差的核心优势
  §3 AUC 与 Cliff's δ 的换算（δ = 2·AUC − 1）与效应量分级
  §4 bootstrap CI 的**可复现性**（固定种子 ⇒ 同输入同 CI）
  §5 翻转率的三口径都要能算，且**分位分档**在单调变换下不变（分档只看序）
  §6 数据缺失时**如实报缺**（不许从旧报告的组均值反推 AUC —— 均值丢了分布形状）

运行：C:\\Python314\\python.exe src\\analysis\\verify_analysis_metrics.py
"""
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / 'src'))

from analysis.backtest_auc import (auc_score, auc_ci, cliff_delta,   # noqa: E402
                                   delta_mag, load_from_report)
from analysis.flip_rate import tierize, threshold_flip, top_idx, bot_idx  # noqa: E402

F = []


def chk(cond, label, detail=''):
    print(f'  {"PASS" if cond else "FAIL"}  {label}' + (f'  |  {detail}' if detail else ''))
    if not cond:
        F.append(label)


print('=' * 72)
print('§1 AUC 定义与边界（方向约定：neg=风险组应得低分）')
print('-' * 72)
chk(auc_score([1, 2, 3], [10, 11, 12]) == 1.0, '完全可分 → 1.0')
chk(auc_score([10, 11, 12], [1, 2, 3]) == 0.0, '完全反向 → 0.0')
chk(abs(auc_score([1, 2, 3, 4], [1, 2, 3, 4]) - 0.5) < 1e-9, '同分布 → 0.5')
chk(auc_score([5, 5, 5], [5, 5, 5]) == 0.5, '全平局 → 0.5（不虚报可分）')
chk(auc_score([2], [1, 3]) == 0.5, '单点中点 → 0.5（手算核对）')
chk(auc_score([1], [2, 3]) == 1.0, '单点全优 → 1.0（手算核对）')
chk(auc_score([], [1, 2]) is None, '空组 → None（不编数）')
chk(auc_score([1, 2], []) is None, '空对照 → None')

print('\n§2 AUC 抗离群（相对均值差的核心优势）')
print('-' * 72)
# 把最高分从 12 拉到 1e6：均值差会爆炸，AUC 只挪一点点（只改排序不改变序）
_base = auc_score([1, 2, 3], [10, 11, 12])
_out = auc_score([1, 2, 3], [10, 11, 1e6])
chk(_base == 1.0 and _out == 1.0,
    '极值不改变 AUC（同序）', f'{_base} → {_out}')
# 插入一个位于中间的极端值：只影响一个点对的排序
_mid = auc_score([1, 2, 3], [10, 2.5, 12])
chk(0.0 < _mid < 1.0, '插入中间值 → AUC 部分下降（非 0/1 跳变）', str(_mid))

print('\n§3 Cliff δ 与效应量分级（δ = 2·AUC − 1）')
print('-' * 72)
chk(cliff_delta(0.5) == 0.0, 'AUC 0.5 → δ 0')
chk(cliff_delta(1.0) == 1.0, 'AUC 1.0 → δ 1', str(cliff_delta(1.0)))
chk(cliff_delta(0.25) == -0.5, 'AUC 0.25 → δ -0.5', str(cliff_delta(0.25)))
chk(delta_mag(0.1) == '微不足道', '|δ|=0.1 → 微不足道')
chk(delta_mag(0.2) == '小', '|δ|=0.2 → 小')
chk(delta_mag(0.4) == '中', '|δ|=0.4 → 中')
chk(delta_mag(0.5) == '大', '|δ|=0.5 → 大')
# 传两组分数（等价路径）
chk(cliff_delta([1, 2, 3], [10, 11, 12]) == 1.0, '传两组分数 → δ 1')

print('\n§4 bootstrap CI 可复现（固定种子）')
print('-' * 72)
_ci1 = auc_ci([1, 5, 9, 3], [4, 6, 2, 8], n_boot=300)
_ci2 = auc_ci([1, 5, 9, 3], [4, 6, 2, 8], n_boot=300)
chk(_ci1 == _ci2, '同输入同 CI（种子固定）', f'{_ci1} == {_ci2}')
_ci3 = auc_ci([1, 2, 3], [10, 11, 12], n_boot=300)
chk(_ci3 == (1.0, 1.0), '完全可分 → CI 收敛到 1.0', str(_ci3))
_lo, _hi = auc_ci([1, 5, 9, 3], [4, 6, 2, 8], n_boot=300)
chk(_lo <= _hi, 'CI 下界 ≤ 上界', f'[{_lo}, {_hi}]')

print('\n§5 翻转率三口径')
print('-' * 72)
# 分档：单调变换下不变（分位分档只看序）
_p = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
_t1 = tierize(_p, n_tier=3)
_t2 = tierize([v ** 3 for v in _p], n_tier=3)     # 单调变换
chk(_t1 == _t2, '分档对单调变换不变（只看序）', f'{_t1} vs {_t2}')
chk(set(_t1) == {0, 1, 2}, '三档都出现', str(sorted(set(_t1))))
chk(tierize([1.0, 2.0], n_tier=3) == [0, 2] or tierize([1.0, 2.0], n_tier=3) == [0, 1],
    '小样本分档不崩', str(tierize([1.0, 2.0], n_tier=3)))
# 阈值翻转
_fr, _k = threshold_flip([1.0, 5.0], [1.0, 5.0], thr=3.0)
chk(_fr == 0.0 and _k == 0, '同分布 → 0 翻转')
_fr2, _k2 = threshold_flip([1.0, 5.0], [5.0, 1.0], thr=3.0)
chk(_fr2 == 1.0 and _k2 == 2, '完全对调 → 100% 翻转', f'{_fr2}')
# Top/Bottom 名单
chk(top_idx([1, 2, 3, 4, 5], k=2) == {4, 3}, 'Top-2 取最大两个', str(top_idx([1, 2, 3, 4, 5], k=2)))
chk(bot_idx([1, 2, 3, 4, 5], k=2) == {0, 1}, 'Bottom-2 取最小两个', str(bot_idx([1, 2, 3, 4, 5], k=2)))

print('\n§6 缺数据要如实报缺（不许从组均值反推 AUC）')
print('-' * 72)
chk(load_from_report(str(_ROOT / '_backtest_transfer.txt')) is None,
    'load_from_report 恒返回 None（均值丢了分布形状，反推不出 AUC）')

print('\n§7 接线：两个分析脚本都要能 --help 式导入（不崩）')
print('-' * 72)
_src_auc = (_ROOT / 'src' / 'analysis' / 'backtest_auc.py').read_text(encoding='utf-8')
chk('BOOT_SEED' in _src_auc and 'seed=BOOT_SEED' in _src_auc,
    'bootstrap 种子固定（报告可复现）')
chk('Mann-Whitney' in _src_auc or '秩和' in _src_auc,
    'AUC 用秩和（Mann-Whitney）实现，非梯形积分')
_src_fr = (_ROOT / 'src' / 'analysis' / 'flip_rate.py').read_text(encoding='utf-8')
chk('下界代理' in _src_fr,
    '翻转率显式声明是"结论翻转率的下界代理"（不自称完整定义）')
chk('已知局限' in _src_fr, '未重跑整引擎 × λ 网格 记为已知局限')

print('\n' + '=' * 72)
print(f'结论：{"全部通过" if not F else str(len(F)) + " 项 FAIL"}')
print('=' * 72)
for x in F:
    print(f'  FAIL  {x}')
sys.exit(1 if F else 0)
