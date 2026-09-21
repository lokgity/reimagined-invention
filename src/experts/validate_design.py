# -*- coding: utf-8 -*-
"""validate_design.py —— 专家设计稿自洽性校验
=============================================================================
作用：把 `src/experts/*.md` 的 frontmatter 当**可断言数据**校验一遍。
它**不参与运行时**，不改任何链路——只防"设计稿写飘了"。

为什么值得单独存在（答辩口径）：
  "每个专家 = 一个 md 文件"这个说法要成立，`tools` / `requires` /
  `output_contract` 就**必须是机器可读、可校验的**，否则它只是换个人设的幌子。
  本脚本把这一点变成可运行的证据。

⚠️ **校验规则不在本文件里定义。** 单一真源是 `registry.py`
   （`VOCAB` / `REQUIRED` / `GROUPS` / `EXPECTED_IDS` / `collect_errors`）。
   本脚本只负责把它们跑一遍、打印成人能看的报告。
   分成两份规则必然漂移 —— 而"规则本身写错"这个坑已经踩过一次：
   初版把 `requires: []`（零依赖，model_auditor 的正当用法）误判为"缺必填"。
   **规则也需要被验证**，所以只留一份。

跑法：
    C:\\Python314\\python.exe src/experts/validate_design.py
    退出码 1 = 校验未过（与 run_regression.py 的约定一致）

历史：首次运行时抓到两个真问题（已修）——
  1. `franchise_advisor.md` 的 `fallback` 以反引号开头 → YAML 非法
     （YAML 里裸标量不能以 `` ` `` 起头）；
  2. 校验规则本身把零依赖误判为缺必填（见上）。
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / '.pylibs'))

import yaml                                                    # noqa: E402
from experts.registry import (collect_errors, COMMON_ID,       # noqa: E402
                              EXPECTED_IDS, VOCAB)


def _meta(p):
    txt = p.read_text(encoding='utf-8')
    if not txt.startswith('---\n'):
        raise ValueError('无 frontmatter')
    return yaml.safe_load(txt.split('---\n', 2)[1])


def main():
    fails = collect_errors()
    lines, seen, blocked = [], {}, []

    for p in sorted(HERE.glob('*.md')):
        if p.name == 'README.md':
            continue
        try:
            d = _meta(p)
        except Exception as e:
            lines.append(f'  ??   {p.name:<24} frontmatter 解析失败：{e}')
            continue
        if p.name == f'{COMMON_ID}.md':
            lines.append('  OK   _common.md（公共铁律，唯一一份，禁止复制）')
            continue
        seen[d.get('id')] = p.name
        if d.get('status') == 'blocked':
            blocked.append(d.get('name'))
        lines.append(f'  OK   {p.stem:<24} {d.get("alias")}·{d.get("name")} '
                     f'blurb={len(str(d.get("blurb") or ""))}字 '
                     f'tools={len(d.get("tools") or []):<2} '
                     f'forbids={len(d.get("forbids") or []):<2} '
                     f'kb_tags={d.get("kb_tags")} '
                     f'requires={d.get("requires")} '
                     f'status={d.get("status")}')

    out = ['=' * 66,
           '专家设计稿校验（src/experts/）',
           '=' * 66]
    out += lines
    out.append('-' * 66)
    out.append(f'工具词汇表登记数 = {len(VOCAB)}')
    out.append(f'专家数 = {len(seen)}（期望 {len(EXPECTED_IDS)}）')
    out.append(f'blocked（不得出现在用户可选列表）= {blocked or "无"}')
    out.append(f'FAILS = {len(fails)}')
    out += [f'  FAIL {f}' for f in fails]
    out.append('结论：' + ('全部通过' if not fails else '有失败'))
    report = '\n'.join(out)
    # 自己落盘（与 run_regression.py 一致）：PowerShell 管道转码会把中文搞成乱码，
    # 让脚本写文件才是可靠路径（本项目已踩过多次）。
    (HERE / '_design_report.txt').write_text(report, encoding='utf-8')
    print(report)
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
