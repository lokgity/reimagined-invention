# -*- coding: utf-8 -*-
"""make_sample_report.py —— 生成《店铺经营月报》填写样例（md / html）
==========================================================================
数据源是 `report_sample.SAMPLE`（唯一一份），本脚本只负责"读空白表 → 填 → 落盘"。

用法：
    C:\\Python314\\python.exe src/analysis/make_sample_report.py
        [--stage2 <目录>]      # 额外把 HTML 写到该目录（交付流水线的 stage2 产物）

输出：
    docs/店铺经营月报-样例.md     中间稿
    docs/店铺经营月报-样例.html   交付源（→ 转 docx 的就是它）

⚠️ 落盘后**必须**跑两道验：
    · 静态：src/analysis/verify_report_form.py  §6 用真实抽取器解样例
    · 实机：src/analysis/live_report_probe.py --sample 解成品 docx
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))

from report_sample import (                       # noqa: E402
    BLANK_MD, BLANK_HTML, SAMPLE_MD, SAMPLE_HTML, SAMPLE,
    build_sample_md, build_sample_html,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage2', default=None,
                    help='额外写出 HTML 的目录（如 output/<rid>/stage2/intermediate）')
    a = ap.parse_args()

    if not BLANK_MD.exists() or not BLANK_HTML.exists():
        print(f'空白表不存在：{BLANK_MD} / {BLANK_HTML}')
        return 2

    md = build_sample_md(BLANK_MD.read_text(encoding='utf-8'))
    html = build_sample_html(BLANK_HTML.read_text(encoding='utf-8'))

    SAMPLE_MD.write_text(md, encoding='utf-8')
    SAMPLE_HTML.write_text(html, encoding='utf-8')
    print(f'写出 {SAMPLE_MD.relative_to(ROOT)}  （{len(md)} 字符）')
    print(f'写出 {SAMPLE_HTML.relative_to(ROOT)}（{len(html)} 字符）')

    if a.stage2:
        out = Path(a.stage2)
        out.mkdir(parents=True, exist_ok=True)
        (out / 'report.html').write_text(html, encoding='utf-8')
        print(f'写出 {out / "report.html"}')

    # 报一遍残留的全角空格。⚠️ 残留不是 0，而且**不该是 0**：CSS 页脚、
    # 副标题分隔符、`第一章　怎么用` 这类章节标题本来就用全角空格，它们前面
    # 没有口径标签，`blank_span` 不会把它们当填写位。真正的判据是"还有没有
    # 没填的栏"，那由 `verify_report_form.py` §6 逐栏断言，不靠这个计数。
    left = html.count('\u3000')
    n_slot = sum(1 for lb, _, _ in SAMPLE if lb in html)
    print(f'样例 HTML 残留全角空格：{left} 个（结构性分隔符，非填写位）')
    print(f'十项口径标签均在文中：{n_slot}/10')
    return 0


if __name__ == '__main__':
    sys.exit(main())
