# -*- coding: utf-8 -*-
"""
report_pdf.py —— 分析报告 PDF 导出
====================================
把一次商铺分析结果渲染成可下载的 PDF（HTML -> Chromium 打印，0 次 API）。
中文用系统字体（Chromium 内置渲染），无需额外字体库。
"""
import html
from datetime import datetime


def _esc(s):
    return html.escape('' if s is None else str(s))


def _fmt(v, dec=0):
    """数字格式化；非数字原样输出"""
    try:
        f = float(v)
        return f'{f:,.0f}' if dec == 0 else f'{f:,.{dec}f}'
    except Exception:
        return '-' if v is None else str(v)


def build_analysis_pdf(result: dict, interpretation: str = '') -> bytes | None:
    """生成分析报告 PDF 字节；失败返回 None。"""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None

    name = result.get('name') or '商铺'
    category = result.get('category') or '-'
    total = result.get('total')
    verdict = result.get('verdict') or ''
    dims = result.get('dims') or {}
    utility = result.get('utility') or {}
    profit = result.get('profit') or {}
    decoration = result.get('decoration') or {}
    evidence = result.get('evidence') or {}
    warnings = result.get('warnings') or []
    ts = datetime.now().strftime('%Y-%m-%d %H:%M')

    # 四维评分表
    dim_rows = ''.join(
        f'<tr><td class="k">{_esc(k)}</td><td class="v">{_fmt(v)}</td></tr>'
        for k, v in dims.items()
    )

    # 水电
    util_rows = ''
    if utility:
        util_rows = (
            f'<tr><td class="k">商业电价</td><td class="v">{_esc(utility.get("电价(元/度)"))} 元/度</td></tr>'
            f'<tr><td class="k">商业水价</td><td class="v">{_esc(utility.get("水价(元/吨)"))} 元/吨</td></tr>'
            f'<tr><td class="k">月用电</td><td class="v">{_fmt(utility.get("月用电(kWh)"))} kWh（¥{_fmt(utility.get("电费(元/月)"))}）</td></tr>'
            f'<tr><td class="k">月用水</td><td class="v">{_fmt(utility.get("月用水(吨)"))} 吨（¥{_fmt(utility.get("水费(元/月)"))}）</td></tr>'
            f'<tr class="hl"><td class="k">月水电合计</td><td class="v">¥{_fmt(utility.get("水电合计(元/月)"))}</td></tr>'
        )

    # 盈利测算
    profit_rows = ''
    if profit:
        payback = profit.get('回本周期(月)')
        pb_txt = f'{_fmt(payback)} 个月' if payback else '难以回本'
        profit_rows = (
            f'<tr><td class="k">预估月流水</td><td class="v">¥{_fmt(profit.get("月流水估算"))}</td></tr>'
            f'<tr><td class="k">月物料成本</td><td class="v">¥{_fmt(profit.get("月物料成本"))}（占流水 {_fmt(profit.get("物料占比"), 2)}）</td></tr>'
            f'<tr><td class="k">月人工</td><td class="v">¥{_fmt(profit.get("月人工"))}（{_fmt(profit.get("人数"))}人 × ¥{_fmt(profit.get("人均月薪"))} 最低工资）</td></tr>'
            f'<tr><td class="k">月租金</td><td class="v">¥{_fmt(profit.get("月租金"))}</td></tr>'
            f'<tr><td class="k">月水电</td><td class="v">¥{_fmt(profit.get("月水电"))}</td></tr>'
            f'<tr><td class="k">月杂费</td><td class="v">¥{_fmt(profit.get("月杂费"))}</td></tr>'
            f'<tr><td class="k">月固定成本</td><td class="v">¥{_fmt(profit.get("月固定成本"))}</td></tr>'
            f'<tr><td class="k">前期投入</td><td class="v">¥{_fmt(profit.get("前期投入"))}（{_esc(profit.get("投入来源"))}）</td></tr>'
            f'<tr><td class="k">装修档次</td><td class="v">{_esc(decoration.get("档次"))}</td></tr>'
            f'<tr class="hl"><td class="k">月净利估算</td><td class="v">¥{_fmt(profit.get("月净利估算"))}</td></tr>'
            f'<tr class="hl"><td class="k">回本周期</td><td class="v">{pb_txt}</td></tr>'
            f'<tr class="hl"><td class="k">盈亏判断</td><td class="v">{_esc(profit.get("盈亏判断"))}</td></tr>'
        )

    # 证据
    evidence_rows = ''
    if evidence:
        evidence_rows = (
            f'<tr><td class="k">周边竞品</td><td class="v">{_fmt(evidence.get("竞品数"))} 家（引力比 {_esc(evidence.get("竞品引力比"))}）</td></tr>'
            f'<tr><td class="k">客群引力累计</td><td class="v">{_esc(evidence.get("客群引力累计"))}</td></tr>'
            f'<tr><td class="k">最近通勤点</td><td class="v">{_fmt(evidence.get("最近通勤点(m)"))}m，500m内 {_fmt(evidence.get("500m内通勤点数"))} 个</td></tr>'
            f'<tr><td class="k">预估月流水</td><td class="v">¥{_fmt(evidence.get("预估月流水"))}，租金占 {_esc(evidence.get("租金占流水比"))}</td></tr>'
        )

    warning_html = ''
    if warnings:
        items = ''.join(f'<li>{_esc(w)}</li>' for w in warnings)
        warning_html = f'<h2>⚠️ 风险警告</h2><ul class="warn">{items}</ul>'

    interp_html = ''
    if interpretation:
        interp_html = f'<h2>📝 AI 解读</h2><div class="interp">{_esc(interpretation)}</div>'

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<style>
  body {{ font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif; color: #1e293b; font-size: 13px; line-height: 1.6; }}
  h1 {{ font-size: 22px; color: #1d4ed8; margin: 0 0 4px; }}
  .sub {{ color: #64748b; font-size: 12px; margin-bottom: 18px; }}
  .score {{ background: linear-gradient(90deg,#2563eb,#3b82f6); color: #fff; padding: 14px 18px; border-radius: 10px; margin-bottom: 16px; }}
  .score b {{ font-size: 20px; }}
  h2 {{ font-size: 15px; color: #1d4ed8; border-left: 4px solid #2563eb; padding-left: 8px; margin: 20px 0 8px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 6px 0; }}
  td {{ padding: 6px 10px; border-bottom: 1px solid #e2e8f0; }}
  td.k {{ color: #475569; width: 38%; }}
  td.v {{ color: #0f172a; font-weight: 600; }}
  tr.hl td {{ background: #eff6ff; }}
  ul.warn li {{ color: #b91c1c; margin: 3px 0; }}
  .interp {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 14px; white-space: pre-wrap; }}
  .foot {{ color: #94a3b8; font-size: 11px; margin-top: 22px; border-top: 1px solid #e2e8f0; padding-top: 8px; }}
</style></head>
<body>
  <h1>🏠 浙里选址 · 商铺分析报告</h1>
  <div class="sub">{_esc(name)} ｜ {_esc(category)} ｜ 生成时间 {ts}</div>
  <div class="score">综合评分：<b>{_fmt(total)} 分</b> —— {_esc(verdict)}</div>

  <h2>📊 四维度评分</h2>
  <table>{dim_rows}</table>

  {('' if not evidence_rows else '<h2>📋 关键证据</h2><table>' + evidence_rows + '</table>')}

  {('' if not util_rows else '<h2>💡 水电成本测算</h2><table>' + util_rows + '</table>')}

  {('' if not profit_rows else '<h2>💰 盈利测算（含人工+物料+装修）</h2><table>' + profit_rows + '</table>')}

  {warning_html}
  {interp_html}

  <div class="foot">⚠️ 本报告基于公开 POI 数据，不含真实人流量与成交租金；水电为参考标准。结论为选址适宜度参考，建议现场复核。由「浙里选址」自动生成。</div>
</body></html>"""

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html_doc, wait_until='load')
            pdf = page.pdf(format='A4', print_background=True,
                           margin={'top': '12mm', 'bottom': '12mm', 'left': '12mm', 'right': '12mm'})
            browser.close()
        return pdf
    except Exception:
        return None
