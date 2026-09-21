# -*- coding: utf-8 -*-
"""run_regression.py —— 批量回归门禁运行器
============================================
把全部验证脚本跑一遍，输出通过/失败汇总，并以退出码表示门禁结论。

- **离线门禁组**：必须 rc=0 且 FAILED=0，否则本脚本退出码为 1。
- **网络依赖组**：信息性汇报，不计入门禁（依赖高德/58/火山方舟可用）。

⚠️ 三个必须知情的实现约定（都踩过坑）：
1. **直跑脚本，不走 `_run.py` 包装层**。`_run.py` 把子进程 stdout 写进
   `_wd_log.txt` 而不转发，本运行器就看不到 `全部 PASS`/`FAIL` 字样
   （第一版 runner 因此把全部套件误报成"未通过"）。
2. **判据是 `rc=0` **且** `FAILED=0`**。各脚本退出码约定不统一
   （`sys.exit(1 if FAIL else 0)` / 靠 `assert` / 有的原先根本不设退出码），
   只看 rc 会漏掉"只打印不退出"的脚本，只看文本会漏掉 assert 类脚本。
3. 必须设 `PYTHONPATH=.pylibs`；`cwd` 设为项目根（脚本自己会再插 `src`）。

用法：C:\\Python314\\python.exe src/analysis/run_regression.py
输出：同目录 `_regression_report.txt`
"""
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PY = r'C:\Python314\python.exe'

OFFLINE = [
    'test_veto.py',
    'verify_price_ref_determinism.py',
    'verify_elasticity_band.py',
    'verify_brief_smoke.py',
    'verify_brand_card.py',
    'verify_brand_graph.py',
    'verify_brand_closedloop.py',
    'verify_flow_v2.py',
    'verify_flow_graph.py',
    # 2026-09-17 新增：入口B(地点优先) / 候选扩量(抓60展示15) / 租金面积三态。
    # 它抓到过一个**静默退化**：给 band_from_samples 加时间戳时踩了 NameError，
    # 被调用方 except 兜住 → 参考带变 None → "推算租金"全部静默退化成"不可得"。
    # 这种路径没有任何报错，只能靠套件发现。
    'verify_place_first.py',
    'verify_knowledge_rag.py',
    'verify_degrade_fallback.py',
    'verify_store_diagnosis.py',
    # 2026-09-18 新增：《店铺经营月报》表单可读性。桌面那份 Word 是**用户填、机器读**
    # 的输入表，喂给 store_diagnosis_advisor。它抓到过三类"表自己毒自己"的缺陷：
    # 说明文字里写了品类举例/城市清单/「自创品牌」，空表都会被 extract_* 解出值；
    # markdown 有序列表的 "1." 让表体出现数字。这三条都只能靠套件发现 —— 肉眼看着
    # 完全正常的说明文字，在抽取器眼里就是数据。
    'verify_report_form.py',
    'verify_experts.py',
    'verify_ui.py',
    # 2026-09-18 新增：公网访问闸门（口令 / 每 IP 限流 / 全局日预算）。
    # 服务是 `--host 0.0.0.0`，一旦穿透到公网，任何人都能刷服务端的 LLM + 高德额度。
    # 这类"没拦住"在本地**永远看不出来**（内网豁免把本地全放行了），
    # 只有月底账单会告诉你 —— 所以必须用套件把默认值与算术钉死。
    'verify_access_gate.py',
]
NET = ['test_vision_storefront.py', 'test_composite_intent.py',
       'test_expert_functioncalling.py']

L = []


def run(script, offline=False):
    env = dict(os.environ)
    env['PYTHONPATH'] = str(ROOT / '.pylibs')
    env['PYTHONIOENCODING'] = 'utf-8'
    if offline:
        # ⚠️ 离线门禁必须真的离线：§6 给 category_reverse / franchise_advisor
        #    两位专家加了"附加 LLM 解读"，而它们所在节点（reverse_match_node /
        #    collect_brand_node）正是 verify_flow_v2 / verify_brand_* 直接调用的。
        #    不禁用的话这四个"离线"套件会开始打外网 → 变成依赖网络与配额的 flaky 组
        #    （本项目纪律：flaky 组不许进离线门禁）。
        env['ZL_EXPERT_LLM_DISABLE'] = '1'
    r = subprocess.run(
        [PY, str(Path('src') / 'analysis' / script)],
        cwd=str(ROOT), capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=1800, env=env)
    out = (r.stdout or '') + '\n' + (r.stderr or '')
    # 三种失败计数写法都要认（各脚本历史写法不一）
    fails = 0
    for pat in (r'fails\s*=\s*(\d+)', r'FAILED\s*=\s*(\d+)', r'共\s*(\d+)\s*项\s*FAIL'):
        for m in re.finditer(pat, out):
            fails = max(fails, int(m.group(1)))
    return r.returncode, fails, out


def main():
    L.append('=' * 74)
    L.append('离线门禁组（必须 rc=0 且 FAILED=0）')
    L.append('=' * 74)
    gate_bad = []
    for s in OFFLINE:
        rc, fails, _ = run(s)
        ok = (rc == 0 and fails == 0)
        L.append(f'  {"OK  " if ok else "FAIL"} {s:<38} rc={rc} FAILED={fails}')
        if not ok:
            gate_bad.append(f'{s}(rc={rc},FAILED={fails})')
    L.append('')
    L.append('=' * 74)
    L.append('网络依赖组（信息性，不计入门禁）')
    L.append('=' * 74)
    net_bad = []
    for s in NET:
        try:
            rc, fails, _ = run(s)
            L.append(f'  ---- {s:<38} rc={rc} FAILED={fails}')
            if rc != 0 or fails:
                net_bad.append(s)
        except Exception as e:
            L.append(f'  ---- {s:<38} 异常 {e}')
            net_bad.append(s)
    L.append('')
    L.append('=' * 74)
    L.append(f'门禁结论：{"全部通过" if not gate_bad else "有失败 -> " + " / ".join(gate_bad)}')
    L.append(f'离线套件数={len(OFFLINE)}  失败数={len(gate_bad)}  '
             f'（网络组异常 {len(net_bad)}：{", ".join(net_bad) if net_bad else "无"}）')
    (HERE / '_regression_report.txt').write_text('\n'.join(L), encoding='utf-8')
    return 1 if gate_bad else 0


if __name__ == '__main__':
    sys.exit(main())
