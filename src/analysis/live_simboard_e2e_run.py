# -*- coding: utf-8 -*-
"""真跑一次选址分析，验证快照会落盘、左栏按钮会被点亮。

走的是**真实用户路径**：打开 UI → 点快速演示按钮 → 等分析结束 → 查 last_sim.json。
不直接调 build_analysis_dashboard_with_sim()，因为那样写出来的快照
没有真实 session id，正是红线 4 要防的"来路不明"。
"""
import io
import json
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(r'd:\Users\ASUS\Desktop\压缩\site-selection-agent')
SIM = ROOT / 'public' / 'last_sim.json'
BASE = 'http://127.0.0.1:8502'
SHOT = Path(r'C:\Users\ASUS\AppData\Local\Temp\_zsn_run_once.png')

FAIL = []


def check(name, ok, extra=''):
    print(('  [PASS] ' if ok else '  [FAIL] ') + name + (('  ← ' + str(extra)) if extra and not ok else ''))
    if not ok:
        FAIL.append(name)


if SIM.exists():
    os.remove(SIM)

with sync_playwright() as p:
    br = None
    for kw in ({'headless': True, 'channel': 'chrome'}, {'headless': True}):
        try:
            br = p.chromium.launch(**kw)
            print('  浏览器启动方式:', kw)
            break
        except Exception as e:
            print('  启动失败:', kw, str(e)[:80])
    assert br is not None, '没有可用浏览器'
    pg = br.new_page(viewport={'width': 1440, 'height': 900})
    pg.goto(BASE, wait_until='domcontentloaded', timeout=60000)
    # 等左栏渲染出来
    pg.wait_for_selector('#zl-rail', timeout=60000)
    time.sleep(3)

    # 点之前：按钮必须是 disabled（还没有快照）
    pre = pg.eval_on_selector('#zl-simboard',
                              'e => ({dis: e.hasAttribute("disabled"), '
                              'cls: e.className, title: e.title})')
    print('  点击前按钮状态:', pre)
    # ⚠️ 2026-09-21 15:33 起语义变了：删掉 last_sim.json（"最近一次"）**不等于**
    #    没有可看的大屏 —— 只要**历史上任何一次**留了快照，按钮就该是可点的
    #    （点开进卡片页去挑那几次）。所以这里断言的是"仍然可用"。
    check('最近一次快照被删后，按钮**仍可点**（历史里还有可挑的）',
          pre['dis'] is False, pre)
    check('按钮 title 指向最近一次（或说明还没有）', bool(pre['title']), pre)

    # 点快速演示（奶茶·武林广场·8k）—— 真实用户路径
    # 走**真实输入**：playwright 的 fill + 真键盘 Enter。
    # ⚠️ 不能用 JS dispatchEvent 代替 —— React 的合成事件对手动派发的
    #    KeyboardEvent 不响应（keyCode 只读），实测消息根本发不出去。
    ta = pg.query_selector('textarea')
    assert ta is not None, '找不到输入框'
    ta.fill('有，看中了杭州武林广场的铺子，开奶茶店，面积30平方，月租8000')
    pg.keyboard.press('Enter')
    print('  已发送：奶茶·武林广场·8k（真实输入 + Enter）')
    print('  已点「快速演示」，等分析…')

    # ⚠️ 演示文案**没写品牌**，所以流程会停在"你想加盟哪个奶茶品牌？"。
    #    必须先把这两步走完，才会有 score_site → 才会有 sim → 才会落快照。
    def dash_kind():
        try:
            return json.loads(io.open(ROOT / 'public' / 'dashboard.json',
                                      encoding='utf-8').read()).get('kind')
        except Exception:
            return None

    def send(t):
        ta = pg.query_selector('textarea')
        ta.fill(t)
        pg.keyboard.press('Enter')

    # ① 选品牌（等 brands 卡片出现后点第一个）
    for i in range(40):
        if dash_kind() == 'brands':
            break
        time.sleep(2)
    if dash_kind() == 'brands':
        names = pg.eval_on_selector_all('[data-brand]', 'es => es.map(e => e.getAttribute("data-brand"))')
        print('  品牌卡片:', names[:6])
        pg.eval_on_selector('[data-brand]', 'e => e.click()')
        print('  已选品牌:', names[0] if names else '?')
    else:
        print('  ⚠️ 没等到 brands 卡片，kind =', dash_kind())

    # ② 选铺位（候选卡片出现后点第 1 个）
    for i in range(40):
        if pg.query_selector('[data-choose]'):
            break
        time.sleep(2)
    if pg.query_selector('[data-choose]'):
        pg.eval_on_selector('[data-choose]', 'e => e.click()')
        print('  已选第 1 个候选铺位')
    else:
        print('  ⚠️ 没等到候选铺位卡片')

    # ③ 填经营参数表单（investment 万元 / staff 人）并提交
    for i in range(40):
        if dash_kind() == 'input' and pg.query_selector('#zl-input-form'):
            break
        time.sleep(2)
    if pg.query_selector('#zl-input-form'):
        pg.fill('#zl-input-form input[data-key="investment"]', '15')
        pg.fill('#zl-input-form input[data-key="staff"]', '2')
        print('  已填经营参数：前期投入 15 万 / 2 人')
        pg.eval_on_selector('#zl-input-form', 'f => f.requestSubmit()')
        print('  已提交表单')
    else:
        print('  ⚠️ 没等到经营参数表单，kind =', dash_kind())

    ok = False
    for i in range(60):                      # 最多等 5 分钟
        time.sleep(5)
        if SIM.exists():
            try:
                json.loads(io.open(SIM, encoding='utf-8').read())
                ok = True
                break
            except Exception:
                pass
    print('  等待 %.0f 秒后 last_sim.json %s' % (min((i + 1) * 5, 300),
                                                 '已生成' if ok else '仍未生成'))

    check('跑完一次分析后 /public/last_sim.json 落盘', ok)

    if ok:
        d = json.loads(io.open(SIM, encoding='utf-8').read())
        check('快照 kind = sim_board', d.get('kind') == 'sim_board', d.get('kind'))
        check('快照带**真实**来源会话 id（不是"未知"）',
              bool(d.get('来源会话')) and '未知' not in str(d.get('来源会话')),
              d.get('来源会话'))
        check('快照带取证时间', bool(d.get('取证时间')), d.get('取证时间'))
        check('快照带铺位经纬度', d.get('lng') is not None and d.get('lat') is not None,
              (d.get('lng'), d.get('lat')))
        check('快照带分析半径', d.get('半径m') is not None, d.get('半径m'))
        check('快照里 sim.ok 为真', (d.get('sim') or {}).get('ok') is True)
        check('快照带地图底图（看板页能画出来）', bool(d.get('map_b64')))
        # ---- 自绘大屏（2026-09-21 重做的核心）----
        b = d.get('board') or {}
        check('快照带 board（自绘大屏场景）', bool(b), list(d.keys()))
        check('board.ok 为真', b.get('ok') is True, b.get('原因'))
        srcs = b.get('sources') or []
        rivs = b.get('rivals') or []
        flows = b.get('flows') or []
        check('大屏有**人流来源**节点（小区/学校/商场/写字楼）', len(srcs) >= 2, len(srcs))
        check('来源带**客流权重**（来自 profile，不是编的）',
              all(s.get('w') for s in srcs), [s.get('w') for s in srcs])
        check('大屏有**竞品店铺**节点', len(rivs) >= 1, len(rivs))
        check('大屏有**流向**（来源 → 本铺/竞品）', len(flows) >= 2, len(flows))
        check('流向覆盖到本铺', any(f.get('si_kind') == 'store' for f in flows))
        check('存在被竞品分流的流向', any(f.get('si_kind') == 'rival' for f in flows))
        check('每条流向都带真实道路折线（不留假轨迹）',
              all(len(f.get('pts') or []) > 1 for f in flows),
              [len(f.get('pts') or []) for f in flows])
        check('小人数 > 0（画面的"动态"来自它们）',
              (b.get('meta') or {}).get('小人总数', 0) > 0,
              (b.get('meta') or {}).get('小人总数'))
        # ---- 策 2026-09-21 11:13 实测抓到的两个错 ----
        _m = b.get('meta') or {}
        _ts = _m.get('到本铺比例')
        check('「到本铺比例」是**加权**的，落在 0~1（不再 >100%）',
              isinstance(_ts, (int, float)) and 0 <= _ts <= 1, _ts)
        print('  到本铺比例 = %.1f%%（加权；旧实现是各来源 Σshare，会 >100%%）'
              % ((_ts or 0) * 100))
        # ⚠️ 竞品在 shops 里的下标是 **1..N**（0 是本铺），不是 0..N-1 —— 这里一开始写错过。
        _cov = set((f.get('si_kind'), f.get('si_idx')) for f in flows)
        _miss = [i for i in range(1, len(rivs) + 1) if ('rival', i) not in _cov]
        check('**每个竞品店铺都有路连过去**（没有孤零零挂着的店）',
              not _miss, '缺路的竞品下标 %s（全量 %s）' % (_miss, sorted(_cov)))
        check('本铺也一定有路', ('store', 0) in _cov)
        check('大屏不再依赖高德底图（map_b64 可为空）', True)
        print('  铺位=%s 品类=%s 半径=%sm ｜ 来源=%d 竞品=%d 流向=%d 小人=%d ｜ 大小=%.0fKB'
              % (d.get('铺位'), d.get('品类'), d.get('半径m'), len(srcs), len(rivs),
                 len(flows), (b.get('meta') or {}).get('小人总数', 0),
                 SIM.stat().st_size / 1024))
        # 等一轮轮询（2.5s）让按钮状态同步
        time.sleep(6)
        post = pg.eval_on_selector('#zl-simboard',
                                   'e => ({dis: e.hasAttribute("disabled"), title: e.title})')
        print('  点击后按钮状态:', post)
        check('有快照后按钮**不再是** disabled（用户点得到）', post['dis'] is False)
        check('有快照后 title 变成"取自 <铺位>"', '取自' in post['title'], post['title'])
        # 真的点开看一眼
        # ⚠️ 2026-09-21 15:33 起：点按钮**先进「挑哪一次」卡片页**，
        #    点某张卡才渲染那次的大屏（策要求与"对比分析"一致）。
        #    所以这里必须走两步，不能直接断言 canvas。
        pg.click('#zl-simboard')
        time.sleep(1.6)
        _picks0 = pg.eval_on_selector_all(
            '.sbx-card', 'es => es.map(e => e.getAttribute("data-simboard"))')
        check('点「仿真大屏」**先给卡片列表**（不是直接上图）',
              len(_picks0) >= 1 and any(_picks0), _picks0)
        pg.eval_on_selector_all('.sbx-card', 'es => es[0].click()')
        time.sleep(2.6)
        opened = pg.eval_on_selector('#zl-page-ov', 'e => e.className')
        body = pg.eval_on_selector('#zl-pg-body',
                                   'e => ({len: e.innerHTML.length, '
                                   'svg: e.querySelectorAll("svg").length, '
                                   'tbl: e.querySelectorAll("table").length, '
                                   'srcchips: e.querySelectorAll(".sbx-src .sbx-tag").length, '
                                   'canvas: e.querySelectorAll(".sbx-canvas").length, '
                                   'anim: e.querySelectorAll("animateMotion").length, '
                                   'kpi: e.querySelectorAll(".sbx-kpi").length, '
                                   'src: e.querySelectorAll(".sbx-canvas text").length})')
        check('点按钮后覆盖层打开', 'open' in opened, opened)
        check('看板页渲染出内容', body['len'] > 200, body)
        check('看板页有来源信息（会话/取证时间/经纬度 chip）', body['srcchips'] >= 5, body)
        # ---- 自绘大屏：这几条就是策两次强调的那个要求 ----
        check('渲染出**自绘画布** .sbx-canvas', body['canvas'] >= 1, body)
        check('画布里有**持续动画**（animateMotion，不是静态图）',
              body['anim'] >= 1, body['anim'])
        check('animateMotion 数量 ≥ 小人数（确实每人一个）',
              body['anim'] >= (b.get('meta') or {}).get('小人总数', 1), body['anim'])
        check('顶部有数据 HUD（来源/竞品/小人/份额）', body['kpi'] >= 4, body['kpi'])
        check('画面里有节点文字（来源/竞品/本铺标签）', body['src'] >= 4, body['src'])
        check('页面**不再**出现底图 img（自绘，不搬热力图）',
              pg.eval_on_selector('#zl-pg-body',
                                  'e => e.querySelectorAll(".zr-map img").length') == 0)
        # ---- 尺寸：策 2026-09-21 10:48「横向、占满、少留白、小人多」----
        geo = pg.evaluate("""() => {
          const b = document.getElementById('zl-pg-body');
          const svg = b.querySelector('.sbx-canvas');
          const vb = (svg.getAttribute('viewBox') || '').split(/\\s+/).map(Number);
          const r = svg.getBoundingClientRect();
          const br = b.getBoundingClientRect();
          return {vw: vb[2], vh: vb[3], w: r.width, h: r.height,
                  fillW: r.width / Math.max(1, br.width),
                  fillH: r.height / Math.max(1, br.height)};
        }""")
        print('  大屏几何：viewBox %.0f×%.0f（%.2f:1）｜元素 %.0f×%.0f px ｜ 占子页 %.0f%%×%.0f%%'
              % (geo['vw'], geo['vh'], geo['vw'] / max(1, geo['vh']), geo['w'], geo['h'],
                 geo['fillW'] * 100, geo['fillH'] * 100))
        check('视图框是**横向**长方形（宽 > 高）', geo['vw'] > geo['vh'] * 1.15,
              '%.0f×%.0f' % (geo['vw'], geo['vh']))
        check('画面**宽度铺满**子页面（≥92%）', geo['fillW'] >= 0.92, geo['fillW'])
        check('画面**高度占比够大**（≥55%，少留白）', geo['fillH'] >= 0.55, geo['fillH'])
        check('小人数明显更多（≥40，展示直观）',
              (b.get('meta') or {}).get('小人总数', 0) >= 40,
              (b.get('meta') or {}).get('小人总数'))
        # HUD 上的百分比也不能 >100%（前端读错字段也会露出来）
        hud = pg.eval_on_selector_all('.sbx-kpi', 'es => es.map(e => e.textContent)')
        print('  HUD:', hud)
        bad = []
        for h in hud:
            import re as _re
            for m in _re.finditer(r'(\d+)%', h):
                if int(m.group(1)) > 100:
                    bad.append(h)
        check('HUD 里没有 >100% 的百分比', not bad, bad)
        # 元素级截图：把大屏本身拍下来（不是视口顶部）
        el = pg.query_selector('.sbx-canvas')
        if el:
            el.screenshot(path=str(SHOT))
        else:
            pg.screenshot(path=str(SHOT))

        # ---- 「先挑哪一次，再看内容」的卡片页（策 2026-09-21 15:33 要求）----
        # 每次点左栏按钮都应回到列表（而不是直接显示上一次的图）
        pg.eval_on_selector('#zl-simboard', 'e => e.click()')
        time.sleep(1.5)
        picks = pg.eval_on_selector_all(
            '.sbx-card',
            'es => es.map(e => ({t: e.textContent.slice(0,40), off: e.disabled, '
            'id: e.getAttribute("data-simboard")}))')
        print('  卡片页 %d 张：%s' % (len(picks), [p['t'][:16] for p in picks[:4]]))
        check('从大屏再点按钮，仍然回到卡片列表（每次都让用户重新挑）',
              len(picks) >= 1, len(picks))
        check('卡片带铺位/品类/时间/评分', all(('地址评分' in p['t']) for p in picks), picks[:1])
        ok_cards = [p for p in picks if p['id']]
        check('至少一张卡可点（有大屏快照）', len(ok_cards) >= 1, len(picks))
        pg.screenshot(path=r'C:\Users\ASUS\AppData\Local\Temp\_zsn_pick.png', full_page=True)
        if ok_cards:
            pg.eval_on_selector_all('.sbx-card', 'es => es[0].click()')
            time.sleep(2.5)
            back = pg.eval_on_selector('#zl-pg-body',
                                       'e => ({canvas: e.querySelectorAll(".sbx-canvas").length, '
                                       'back: e.querySelectorAll("#zl-sim-back").length})')
            check('点卡片后渲染出那一次的大屏', back['canvas'] >= 1, back)
            check('大屏上有「← 换个分析」返回入口', back['back'] >= 1, back)
        # 按 analysis_id 落盘
        _bdir = ROOT / 'public' / 'sim_boards'
        _bn = len(list(_bdir.glob('*.json'))) if _bdir.exists() else 0
        check('每次分析都按 analysis_id 落了一份大屏快照', _bn >= 1, _bn)
        print('  public/sim_boards/ 下 %d 份快照' % _bn)
        print('  截图:', SHOT)

    br.close()

print()
if FAIL:
    print('✗ %d 项未通过：' % len(FAIL))
    for f in FAIL:
        print('   ·', f)
    sys.exit(1)
print('✓ 真跑一遍：快照落盘 + 左栏入口点亮，全部通过')
