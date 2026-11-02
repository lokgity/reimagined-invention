# -*- coding: utf-8 -*-
"""verify_param_echo.py —— 参数回显 + 租金单位归一化回归（**离线门禁组成员**）
================================================================================
2026-09-28 新增。对应专家评审 P0-1：「参数解析后必须回显确认」。

## 为什么必须有这个套件

五项参数全靠抽取，而商铺租金报价习惯极杂：月租 / 年租 / **元/㎡/天** /
含不含物业费 / "8万"是流水还是租金。**任何一项抽错，引擎都会确定性地
算出一个错误结论** —— 不是随机噪声，是稳定地错。所以这是本项目最贵的
一类错，必须有回归钉住。

### 历史血案（本套件就是为了防它复发）
- "装修预算20万" 被当成年租 20 万 → 租金承受力打 0 分，结论全反（2026-09-14）
- "单杯价当每单金额" → 差 1.7 倍（品牌级口径修正，2026-09-18）
- "3块一平一天" 被读成"月租 3 元" → **差上千倍**（本套件新增，2026-09-28）

## 覆盖
- §1 单价识别（三种语序：正序 / 倒序 / 混序）
- §2 单价 → 月租换算（必须带面积；无面积**不猜**，返回 None）
- §3 常规月租不受影响（无回归）
- §4 历史两个坑不复发（装修预算 / 单杯价语境）
- §5 参数回显字段构造（`_confirm_fields` 真的带出 rent 且标出单位）

运行：C:\\Python314\\python.exe src/analysis/verify_param_echo.py
输出：同目录 _param_echo_report.txt
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / '.pylibs'))
os.environ.setdefault('ZL_EXPERT_LLM_DISABLE', '1')

HERE = Path(__file__).resolve().parent
L, FAILS = [], []


def p(*a):
    s = ' '.join(str(x) for x in a)
    print(s)
    L.append(s)


def check(cond, label, detail=''):
    p(f'  {"PASS" if cond else "FAIL"}  {label}' + (f'  |  {detail}' if detail else ''))
    if not cond:
        FAILS.append(label)


from agent.agent import extract_rent, extract_rent_unit_price  # noqa: E402

p('=' * 72)
p('参数回显 + 租金单位归一化 回归')
p('=' * 72)

# ------------------------------------------------------------------
p('\n[1] 单价识别（三种语序都要认）')
p('-' * 72)
UP_CASES = [
    ('3块一平一天，45平', 3.0, '正序·口语（本项目最危险的写法）'),
    ('2.5元/㎡/天 面积40平米', 2.5, '正序·标准单位'),
    ('租金 3 元/平方米/日', 3.0, '正序·汉字单位'),
    ('每平每天3块，50平', 3.0, '倒序·每/每天'),
    ('一平一天3块 35平', 3.0, '倒序·纯口语'),
    ('一天3块一平 35平', 3.0, '混序·时间段在前'),
]
for txt, exp, note in UP_CASES:
    up, _ = extract_rent_unit_price(txt, area=45)
    check(up == exp, f'{note}：{txt!r} → {exp} 元/㎡/天', f'实得 {up}')

# ------------------------------------------------------------------
p('\n[2] 单价 → 月租换算（× 面积 × 30 天）')
p('-' * 72)
CONV = [
    ('3块一平一天，45平', 45, 4050),      # 3 × 45 × 30
    ('2.5元/㎡/天 面积40平米', 40, 3000),  # 2.5 × 40 × 30
    ('一天3块一平 35平', 35, 3150),        # 3 × 35 × 30
]
for txt, area, exp in CONV:
    r = extract_rent(txt, area=area)
    check(r == exp, f'{txt!r} 面积{area} → 月租 {exp}', f'实得 {r}')

# ⚠️ 无面积时**不猜**（红线）：只认到单价、月租返回 None
up, mo = extract_rent_unit_price('3块一平一天', area=None)
check(up == 3.0 and mo is None, '无面积 → 认到单价 3.0 但月租不给（不猜）',
      f'实得 up={up} mo={mo}')
check(extract_rent('3块一平一天', area=None) is None,
      '无面积时 extract_rent 返回 None（不被读成"月租 3 元"）',
      f'实得 {extract_rent("3块一平一天", area=None)}')

# ------------------------------------------------------------------
p('\n[3] 常规月租写法不受影响（无回归）')
p('-' * 72)
NORMAL = [
    ('月租8000，45平', 45, 8000),
    ('月租1.2万', None, 12000),
    ('租金 12000', None, 12000),
    ('月租 3500 面积30平', 30, 3500),
    ('45平的铺子月租9000', 45, 9000),
    ('租金8000一天', 45, 8000),   # "一天"不是单价语境，不误判
]
for txt, area, exp in NORMAL:
    r = extract_rent(txt, area=area)
    check(r == exp, f'{txt!r} → {exp}', f'实得 {r}')

# ------------------------------------------------------------------
p('\n[4] 历史两个坑不复发')
p('-' * 72)
check(extract_rent('装修预算20万') is None,
      '"装修预算20万" 不当月租（2026-09-14 的坑）',
      f'实得 {extract_rent("装修预算20万")}')
check(extract_rent('前期投入预算15万 3人') is None,
      '"前期投入预算15万" 不当月租',
      f'实得 {extract_rent("前期投入预算15万 3人")}')

# 单价 vs 月租的**倍数**必须量级正确（这是本套件的核心价值）
_misread = extract_rent('3块一平一天，45平', area=45)
check(_misread and _misread >= 4000,
      '单价写法换算后量级正确（≥4000，不是 3）',
      f'实得 {_misread}（错误读法会得到 3）')

# ------------------------------------------------------------------
p('\n[5] 参数回显字段构造（_confirm_fields）')
p('-' * 72)
try:
    # app_chainlit 会 import chainlit，可能不在离线环境；尽力而为
    from ui.app_chainlit import _confirm_fields
    _st = {'category': '奶茶', 'address': '宁波海曙区', 'rent': 4050,
           'area': 45, 'brand': '蜜雪冰城', 'investment': 120000, 'staff': 2}
    _f = _confirm_fields(_st, {'profit': {'月租金': 4050}})
    _keys = [x['key'] for x in _f]
    check('rent' in _keys, '确认卡带出 rent 字段', f'实得 {_keys}')
    check('area' in _keys and 'category' in _keys and 'address' in _keys,
          '确认卡带出 area/category/address', f'实得 {_keys}')
    _rent_f = next((x for x in _f if x['key'] == 'rent'), {})
    check(_rent_f.get('unit') == '元/月', '租金字段标明单位「元/月」',
          f'实得 {_rent_f.get("unit")}')
    check('核对' in (_rent_f.get('note') or ''), '租金字段带"必须核对"提示',
          f'实得 {(_rent_f.get("note") or "")[:30]}')
    check(len(_f) == 7, '7 项参数全部带出', f'实得 {len(_f)}')
except Exception as e:
    p(f'  SKIP  _confirm_fields 不可导入（离线环境缺 chainlit？）：{e}')

# ------------------------------------------------------------------
p('\n' + '=' * 72)
p(f'结论：{"全部通过" if not FAILS else str(len(FAILS)) + " 项 FAIL"}')
p('=' * 72)
for f in FAILS:
    p(f'  FAIL  {f}')

(HERE / '_param_echo_report.txt').write_text('\n'.join(L), encoding='utf-8')
sys.exit(1 if FAILS else 0)
