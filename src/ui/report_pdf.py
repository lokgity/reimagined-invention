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


def _money(v):
    """带货币符号的金额。负号必须在 ¥ 前面：'¥-115,653' 会被读成'¥ 减 11 万'。
    只有月净利类字段可能为负，其余金额恒非负。"""
    try:
        f = float(v)
    except Exception:
        return '-' if v is None else str(v)
    return ('-' if f < 0 else '') + f'¥{abs(f):,.0f}'


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

    # 盈利测算（中性档单点；三档区间见 scenario_rows）
    profit_rows = ''
    if profit:
        payback = profit.get('回本周期(月)')
        pb_txt = f'{_fmt(payback, 1)} 个月' if payback else '难以回本'
        profit_rows = (
            f'<tr><td class="k">预估月流水</td><td class="v">¥{_fmt(profit.get("月流水估算"))}</td></tr>'
            f'<tr><td class="k">月物料成本</td><td class="v">¥{_fmt(profit.get("月物料成本"))}（占流水 {_fmt(profit.get("物料占比"), 2)}）</td></tr>'
            f'<tr><td class="k">月人工</td><td class="v">¥{_fmt(profit.get("月人工"))}（{_fmt(profit.get("人数"))}人 × ¥{_fmt(profit.get("人均月薪"))} 市场工资，含社保 {_esc(_fmt(profit.get("社保负担率"), 2))}）</td></tr>'
            f'<tr><td class="k">月外卖抽成</td><td class="v">¥{_fmt(profit.get("月外卖抽成"))}（外卖占流水 {_esc(_fmt(profit.get("外卖占比"), 2))} × 平台抽成 {_esc(_fmt(profit.get("外卖抽成率"), 2))}）</td></tr>'
            f'<tr><td class="k">月场地附加费</td><td class="v">¥{_fmt(profit.get("月场地附加费"))}（商场扣点/物业费/推广费，占流水 {_esc(_fmt(profit.get("场地附加费率"), 2))}）</td></tr>'
            f'<tr><td class="k">月税</td><td class="v">¥{_fmt(profit.get("月税"))}（占流水 {_esc(_fmt(profit.get("税负率"), 3))}）</td></tr>'
            f'<tr><td class="k">月损耗</td><td class="v">¥{_fmt(profit.get("月损耗"))}（物料报废，占流水 {_esc(_fmt(profit.get("损耗率"), 2))}）</td></tr>'
            f'<tr><td class="k">月租金</td><td class="v">¥{_fmt(profit.get("月租金"))}</td></tr>'
            f'<tr><td class="k">月水电</td><td class="v">¥{_fmt(profit.get("月水电"))}</td></tr>'
            f'<tr><td class="k">月杂费</td><td class="v">¥{_fmt(profit.get("月杂费"))}</td></tr>'
            f'<tr><td class="k">月摊销</td><td class="v">¥{_fmt(profit.get("月摊销"))}（前期投入按 {_fmt(profit.get("摊销月数"))} 个月摊，非现金支出，回本口径已加回）</td></tr>'
            + (f'<tr><td class="k">月品牌费</td><td class="v">¥{_fmt(profit.get("月品牌费"))}（{_esc(profit.get("品牌"))}）</td></tr>'
               if profit.get('月品牌费') else '')
            + (f'<tr><td class="k">人数口径</td><td class="v">{_esc(profit.get("人数口径"))}</td></tr>'
               if profit.get('人数') != profit.get('申报人数') else '') +
            f'<tr><td class="k">月成本合计</td><td class="v">¥{_fmt(profit.get("月成本合计"))}</td></tr>'
            f'<tr><td class="k">前期投入</td><td class="v">¥{_fmt(profit.get("前期投入"))}（{_esc(profit.get("投入来源"))}）</td></tr>'
            f'<tr><td class="k">装修档次</td><td class="v">{_esc(decoration.get("档次"))}</td></tr>'
            f'<tr class="hl"><td class="k">月净利估算（中性档）</td><td class="v">{_money(profit.get("月净利估算"))}</td></tr>'
            f'<tr class="hl"><td class="k">净利率（中性档）</td><td class="v">{_esc(_fmt(profit.get("净利率"), 3))}</td></tr>'
            f'<tr class="hl"><td class="k">回本周期（中性档）</td><td class="v">{pb_txt}</td></tr>'
            f'<tr class="hl"><td class="k">盈亏判断</td><td class="v">{_esc(profit.get("盈亏判断"))}</td></tr>'
        )

    # 三档情景区间：单点数字在 PDF 里更容易被当成承诺，必须把假设摊开
    scenario_rows = ''
    bands = result.get('profit_bands') or {}
    iv = bands.get('区间') or {}
    if iv:
        body = ''
        for n in ('乐观', '中性', '保守'):
            b = bands.get(n) or {}
            if not b:
                continue
            a = b.get('假设') or {}
            bpb = b.get('回本周期(月)')
            body += (
                f'<tr><td class="k">{n}</td><td class="v">'
                f'净利 {_money(b.get("月净利估算"))}／净利率 {_esc(_fmt(b.get("净利率"), 3))}'
                f'／{_fmt(b.get("人数"))} 人／回本 '
                f'{_fmt(bpb, 1) + " 个月" if bpb else "难以回本"}'
                f'（假设：场地附加 {_esc(_fmt(a.get("场地附加费率"), 2))}、'
                f'税 {_esc(_fmt(a.get("税负率"), 3))}、损耗 {_esc(_fmt(a.get("损耗率"), 2))}、'
                f'人均 {_fmt(a.get("人均日单量"))} 单/天）</td></tr>')
        scenario_rows = (
            body
            + f'<tr class="hl"><td class="k">区间结论</td><td class="v">{_esc(iv.get("结论"))}</td></tr>'
            + f'<tr><td class="k">口径声明</td><td class="v">{_esc(iv.get("口径"))}</td></tr>'
        )

    # 口径区间（价格-单量弹性未标定）：与三档情景**正交**——那三档变的是成本假设
    # （扣点/税/损耗/产能），这一档变的是需求假设（日单量跟不跟客单价动）。
    # PDF 会被打印、被当成承诺，这一节不能省。
    caliper_rows = ''
    _cal = result.get('口径区间') or {}
    _civ = _cal.get('区间') or {}
    if _civ:
        _cbody = ''
        for _t in (_cal.get('档位') or []):
            _tpb = _t.get('回本周期(月)')
            _cbody += (
                f'<tr><td class="k">{_esc(_t.get("口径"))}</td><td class="v">'
                f'月流水 {_money(_t.get("月流水"))}／净利 {_money(_t.get("月净利"))}'
                f'／{_fmt(_t.get("日单量参考"))} 单/天·{_fmt(_t.get("人数"))} 人'
                f'／回本 {_fmt(_tpb, 1) + " 个月" if _tpb else "难以回本"}'
                f'（{_esc(_t.get("角色"))}）<br/>{_esc(_t.get("说明"))}</td></tr>')
        _pslo, _pshi = _civ.get('月流水区间(元/月)') or (None, None)
        _pnlo, _pnhi = _civ.get('月净利区间(元/月)') or (None, None)
        caliper_rows = (
            _cbody
            + f'<tr class="hl"><td class="k">月流水区间</td><td class="v">'
              f'{_money(_pslo)} ~ {_money(_pshi)}</td></tr>'
            + f'<tr class="hl"><td class="k">月净利区间</td><td class="v">'
              f'{_money(_pnlo)} ~ {_money(_pnhi)}</td></tr>'
            + f'<tr class="hl"><td class="k">区间结论</td><td class="v">{_esc(_civ.get("结论"))}</td></tr>'
            + f'<tr><td class="k">口径声明</td><td class="v">{_esc(_civ.get("口径"))}</td></tr>'
        )

    # 证据
    evidence_rows = ''
    if evidence:
        _pc = result.get('客单价校正') or {}
        _price = evidence.get('客单价')
        _price_row = (
            f'<tr><td class="k">客单价</td><td class="v">¥{_price:g}'
            f'（{_esc(evidence.get("客单价来源"))}）'
            + (f'；品类画像 ¥{_pc.get("品类画像客单价")}，相差 {_pc.get("校正倍数")} 倍'
               if _pc.get('校正倍数') else '')
            + '</td></tr>') if _price else ''
        _pc_row = (f'<tr><td class="k">客单价校正口径</td>'
                   f'<td class="v">{_esc(_pc.get("口径"))}</td></tr>') if _pc.get('口径') else ''
        evidence_rows = (
            f'<tr><td class="k">周边竞品</td><td class="v">{_fmt(evidence.get("竞品数"))} 家（捕获份额 {_esc(_fmt(round((evidence.get("捕获份额P") or 0) * 100, 1)))}%）</td></tr>'
            f'<tr><td class="k">客群引力累计</td><td class="v">{_esc(evidence.get("客群引力累计"))}</td></tr>'
            f'<tr><td class="k">最近通勤点</td><td class="v">{_fmt(evidence.get("最近通勤点(m)"))}m，500m内 {_fmt(evidence.get("500m内通勤点数"))} 个</td></tr>'
            f'<tr><td class="k">预估月流水</td><td class="v">¥{_fmt(evidence.get("预估月流水"))}，租金占 {_esc(evidence.get("租金占流水比"))}</td></tr>'
            + _price_row + _pc_row
        )

    warning_html = ''
    if warnings:
        items = ''.join(f'<li>{_esc(w)}</li>' for w in warnings)
        warning_html = f'<h2>⚠️ 风险警告</h2><ul class="warn">{items}</ul>'

    interp_html = ''
    if interpretation:
        interp_html = f'<h2>📝 AI 解读</h2><div class="interp">{_esc(interpretation)}</div>'

    # 门头照分析（视觉模型）
    storefront = result.get('storefront') or {}
    storefront_html = ''
    if storefront:
        sf_rows = (
            f'<tr><td class="k">招牌文字</td><td class="v">{_esc(storefront.get("招牌文字") or "未识别")}</td></tr>'
            + (f'<tr><td class="k">识别品牌</td><td class="v">{_esc(storefront.get("识别品牌"))}</td></tr>'
               if storefront.get('识别品牌') else '') +
            f'<tr><td class="k">装修档次</td><td class="v">{_fmt(storefront.get("装修档次"))} / 5</td></tr>'
            f'<tr><td class="k">门头可见度</td><td class="v">{_fmt(storefront.get("门头可见度"))} / 5</td></tr>'
            f'<tr><td class="k">卫生观感</td><td class="v">{_fmt(storefront.get("卫生观感"))} / 5</td></tr>'
            f'<tr class="hl"><td class="k">门头形象分</td><td class="v">{_fmt(storefront.get("形象分"), 1)} 分（权重 {_esc(_fmt(storefront.get("权重占比"), 2))}）</td></tr>'
            f'<tr><td class="k">总分变化</td><td class="v">{_fmt(storefront.get("照片前总分"), 1)} → {_fmt(storefront.get("照片后总分"), 1)} 分</td></tr>'
            f'<tr><td class="k">照片观察</td><td class="v">{_esc(storefront.get("观察描述"))}</td></tr>'
            f'<tr><td class="k">形象建议</td><td class="v">{_esc(storefront.get("经营建议"))}</td></tr>'
        )
        storefront_html = ('<h2>📷 门头照分析（视觉模型）</h2><table>' + sf_rows + '</table>'
                           '<div class="sub">注：以上为门头照片的视觉证据，仅反映拍摄时刻状态；'
                           '不影响流水/成本/回本测算，建议结合不同时段实地复核。</div>')

    # 竞品口碑画像（高德公开字段）
    ci = result.get('competitor_insight') or {}
    competitor_html = ''
    if ci:
        rat = ci.get('口碑分') or {}
        cost = ci.get('客单价带') or {}
        check = ci.get('客单价现实校验') or {}
        top_brands = '、'.join(f'{b["品牌"]}({b["门店数"]}家)' for b in (ci.get('头部品牌') or [])[:3]) or '无明显连锁'
        hot = '、'.join(w['词'] for w in (ci.get('招牌热词') or [])[:8])
        ci_rows = (
            f'<tr><td class="k">竞品样本</td><td class="v">{_fmt(ci.get("样本数"))} 家（周边 1000m，平均距离 {_fmt(ci.get("平均距离(m)"))}m）</td></tr>'
            + (f'<tr><td class="k">口碑分</td><td class="v">均 {_esc(rat.get("均值"))} / 中位 {_esc(rat.get("中位"))} / 区间 {_esc(rat.get("最低"))}~{_esc(rat.get("最高"))}</td></tr>' if rat else '')
            + (f'<tr><td class="k">人均价格带</td><td class="v">P25 ¥{_esc(cost.get("P25"))} / 中位 ¥{_esc(cost.get("中位"))} / P75 ¥{_esc(cost.get("P75"))}</td></tr>' if cost else '')
            + f'<tr><td class="k">连锁占比 / 集中度</td><td class="v">{_esc(_fmt((ci.get("连锁占比") or 0) * 100))}% ／ HHI {_esc(ci.get("品牌集中度HHI"))}</td></tr>'
            f'<tr><td class="k">头部品牌</td><td class="v">{_esc(top_brands)}</td></tr>'
            f'<tr><td class="k">夜间营业 / 团购</td><td class="v">{_fmt(ci.get("夜间营业门店数"))} 家营业至 22 点后 ／ '
            + (f'{_fmt(ci.get("团购活跃门店数"))} 家做团购' if ci.get('团购活跃门店数') is not None
               else '团购字段高德未回填（不作判断）') + '</td></tr>'
            + (f'<tr><td class="k">招牌热销词</td><td class="v">{_esc(hot)}</td></tr>' if hot else '')
            + (f'<tr class="hl"><td class="k">客单价假设校验</td><td class="v">{_esc(check.get("判断"))}：{_esc(check.get("说明"))}</td></tr>' if check else '')
        )
        competitor_html = ('<h2>🔍 周边竞品口碑画像</h2><table>' + ci_rows + '</table>'
                           '<div class="sub">注：' + _esc(ci.get('数据局限')) + '</div>')

    # 结论横幅：位置分与综合结论必须双轴陈述，否则"93.7 分 + 不能签"看起来像自相矛盾
    veto = result.get('veto') or {}
    rl = result.get('rent_limits') or {}
    # 双轴：地址评分（位置好不好）× 经营评分（能不能赚钱）。结论以经营评分为准。
    _biz = result.get('经营评分') or {}
    _bs = _biz.get('分数')
    _bb = _biz.get('区间')
    if _bs is not None:
        biz_txt = (f'经营评分：<b>{_bs} 分</b>'
                   + (f'（三档区间 {_bb[0]}~{_bb[1]}）' if _bb else '')
                   + f' —— {_esc(_biz.get("结论") or "")}'
                   + ('　<span class="vnote">⚠️ 一票否决已触发，分数封顶 59</span>'
                      if _biz.get('一票否决封顶') else ''))
    else:
        biz_txt = f'经营评分：不出分（{_esc(_biz.get("不可得原因") or "数据不足")}）'
    pos_verdict = veto.get('位置分结论') or verdict
    if veto.get('触发'):
        verdict_html = (
            f'<div class="score veto">位置分：<b>{_fmt(total)} 分</b>（{_esc(pos_verdict)}）'
            f'<br>{biz_txt}'
            f'<br>综合结论：<b>{_esc(verdict)}</b> —— {_esc(veto.get("原因") or "")}'
            f'<br><span class="vnote">位置分高不能抵消亏损：加权是补偿性的，"这个租金下亏钱"是非补偿性硬约束，'
            f'一票否决。</span></div>'
        )
    else:
        verdict_html = (f'<div class="score">地址评分：<b>{_fmt(total)} 分</b>（{_esc(pos_verdict)}）'
                        f'<br>{biz_txt}</div>')

    # 租金临界点（纯本地二分反解，0 次 API）：谈判桌上的目标价
    rent_html = ''
    if rl:
        be = rl.get('盈亏平衡月租')
        cap = rl.get('回本达标月租上限')
        rent_now = profit.get('月租金') or result.get('monthly_rent') or 0
        be_txt = (f'¥{_fmt(be)}（当前月租 ¥{_fmt(rent_now)}，'
                  + (f'安全垫 ¥{_fmt(be - rent_now)}）' if be >= rent_now
                     else f'已超出 ¥{_fmt(rent_now - be)}）') if be
                 else '不存在——免租也亏损，问题不在租金')
        from engine.scoring import PAYBACK_LIMIT_MONTHS
        _cap_gap = (f'（比"只求不亏"的 ¥{_fmt(be)} 再低 ¥{_fmt(be - cap)}）'
                    if be and cap and cap < be else '')
        rl_rows = (
            f'<tr class="hl"><td class="k">盈亏平衡月租（月净利=0）</td><td class="v">{be_txt}</td></tr>'
            + (f'<tr><td class="k">{PAYBACK_LIMIT_MONTHS} 个月回本月租上限</td>'
               f'<td class="v">¥{_fmt(cap)}{_cap_gap}</td></tr>' if cap else '')
            + f'<tr><td class="k">免租压力测试</td><td class="v">月净利 {_money(rl.get("免租月净利"))}，'
              f'回本 {(_fmt(rl.get("免租回本周期(月)"), 1) + " 个月") if rl.get("免租回本周期(月)") else "难以回本"}</td></tr>'
        )
        rent_html = ('<h2>🎯 租金临界点（承受力天花板，非开价）</h2><table>' + rl_rows + '</table>'
                     '<div class="sub">注：由盈利模型对月租单调递减的性质二分反解得出，'
                     '已含 0.6 保守爬坡系数；未达盈亏平衡月租即视为不能签。</div>')

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<style>
  body {{ font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif; color: #1e293b; font-size: 13px; line-height: 1.6; }}
  h1 {{ font-size: 22px; color: #1d4ed8; margin: 0 0 4px; }}
  .sub {{ color: #64748b; font-size: 12px; margin-bottom: 18px; }}
  .score {{ background: linear-gradient(90deg,#2563eb,#3b82f6); color: #fff; padding: 14px 18px; border-radius: 10px; margin-bottom: 16px; }}
  .score b {{ font-size: 20px; }}
  .score.veto {{ background: linear-gradient(90deg,#b91c1c,#ef4444); }}
  .score .vnote {{ font-size: 11.5px; opacity: .92; }}
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
  <h1>🏠 址南针 · 商铺分析报告</h1>
  <div class="sub">{_esc(name)} ｜ {_esc(category)} ｜ 生成时间 {ts}</div>
  {verdict_html}

  <h2>📊 维度评分（{len(dims)} 项）</h2>
  <table>{dim_rows}</table>

  {('' if not evidence_rows else '<h2>📋 关键证据</h2><table>' + evidence_rows + '</table>')}

  {('' if not util_rows else '<h2>💡 水电成本测算</h2><table>' + util_rows + '</table>')}

  {('' if not profit_rows else '<h2>💰 盈利测算·中性档（人工含社保·外卖抽成·场地附加·税·损耗·投入摊销·品牌费）</h2><table>' + profit_rows + '</table>')}

  {('' if not scenario_rows else '<h2>📊 三档情景区间（同一铺子，不同经营假设）</h2><table>' + scenario_rows + '</table>')}

  {('' if not caliper_rows else '<h2>🎯 口径区间（同一铺子，两种需求假设：日单量跟不跟客单价动）</h2><table>' + caliper_rows + '</table>')}

  {rent_html}

  {storefront_html}

  {competitor_html}

  {warning_html}
  {interp_html}

  <div class="foot">⚠️ 本报告基于公开 POI 数据，不含真实人流量与成交租金；水电为参考标准。成本模型中的商场扣点、税负、物料损耗、人均产能四项为<b>假设区间，非实测数据</b>，故以乐观/中性/保守三档并列呈现而非单一数字。另：日单量基准由<b>混合品牌</b>门店样本标定，未随品牌客单价联动，而<b>需求量—价格弹性未被标定</b>，故另附「口径区间」两端；本报告所有单点数字均取自「单量刚性」一端，不是区间中点。结论为选址适宜度参考，建议现场复核。由「址南针」自动生成。</div>
</body></html>"""

    try:
        with sync_playwright() as p:
            # 优先系统 Chrome（避免依赖 Playwright 自带浏览器被清理）
            try:
                browser = p.chromium.launch(headless=True, channel="chrome")
            except Exception:
                try:
                    browser = p.chromium.launch(headless=True)
                except Exception as exc:
                    raise RuntimeError(
                        'Playwright Chromium 不可用；请在部署构建阶段运行 '
                        '`playwright install --with-deps chromium`'
                    ) from exc
            page = browser.new_page()
            page.set_content(html_doc, wait_until='load')
            pdf = page.pdf(format='A4', print_background=True,
                           margin={'top': '12mm', 'bottom': '12mm', 'left': '12mm', 'right': '12mm'})
            browser.close()
        return pdf
    except Exception:
        return None
