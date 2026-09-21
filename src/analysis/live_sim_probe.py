# -*- coding: utf-8 -*-
"""实机取证：仿真数据看板（小人沿马路走）在真浏览器里到底渲染成什么样。

只做三件事：
  ① 发一句完整分析 → 等右侧工作台出现
  ② 检查地图上的覆盖层：svg / 折线 path / animateMotion（小人）/ 图注 chips
  ③ 截图存证（_ui_shots/21_sim_dashboard.png）
"""
import io
import json
import sys
from pathlib import Path

ROOT = Path(r'd:/Users/ASUS/Desktop/压缩/site-selection-agent')
sys.path.insert(0, str(ROOT / 'src'))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

URL = 'http://127.0.0.1:8502'
SHOTS = ROOT / '_ui_shots'
SHOTS.mkdir(exist_ok=True)
SNAP = SHOTS / '_dash_snapshot.json'

MSG = '宁波天一广场 · 奶茶 · 30㎡ · 月租 12000 · 预算 20万 · 蜜雪冰城'

FAIL = []


def check(name, ok, extra=''):
    print(('  [PASS] ' if ok else '  [FAIL] ') + name + (('  ← ' + str(extra)) if extra and not ok else ''))
    if not ok:
        FAIL.append(name)


from playwright.sync_api import sync_playwright          # noqa: E402

with sync_playwright() as pw:
    br = None
    for kw in ({'headless': True, 'channel': 'chrome'},
               {'headless': True, 'executable_path': pw.chromium.executable_path},
               {'headless': True}):
        try:
            br = pw.chromium.launch(**kw)
            print('浏览器启动方式:', json.dumps(kw, ensure_ascii=False))
            break
        except Exception as e:                            # noqa: BLE001
            print('  启动失败，换下一种:', str(e)[:70])
    if br is None:
        print('★ 三种方式都失败，无法取证')
        sys.exit(1)
    pg = br.new_page(viewport={'width': 1600, 'height': 950})
    pg.goto(URL, wait_until='load', timeout=60000)
    pg.wait_for_timeout(6000)

    def _send(text):
        for sel in ('#chat-input', 'textarea[data-testid="chat-input"]', 'textarea'):
            el = pg.query_selector(sel)
            if not el:
                continue
            try:
                el.click()
                el.fill(text)
                pg.wait_for_timeout(250)
                pg.keyboard.press('Enter')
                return sel
            except Exception:                             # noqa: BLE001
                continue
        return None

    # ---- 触发一次完整分析：走**快速演示**按钮 ----
    # 为什么不打字：实测把「宁波天一广场 · 奶茶 · 30㎡ · 月租 12000 · 预算 20万」
    # 发出去，会被判成「**铺位未定**」→ 去抓在租商铺 → 天一广场没抓到 →
    # **流程直接结束、根本不进分析**（三次复现，消息确实上屏了）。
    # 快速演示按钮是策为演示固化好的入口，走的是完整分析链。
    SEL_HD = '[data-group="demo"] .zl-group-hd'
    SEL_BTN = '[data-group="demo"] .zl-btn'
    pg.evaluate("(s) => { var h = document.querySelector(s);"
                " if (h && !h.parentElement.classList.contains('open')) h.click(); }", SEL_HD)
    pg.wait_for_timeout(700)
    demos = pg.evaluate(
        "(s) => Array.from(document.querySelectorAll(s)).map("
        "b => ({cmd: b.getAttribute('data-cmd'),"
        " txt: (b.innerText || '').replace(/\\s+/g, ' ').trim()}))", SEL_BTN)
    print('演示按钮:', json.dumps(demos, ensure_ascii=False)[:400])
    assert demos, '快速演示组里没有按钮 —— 前置条件不成立'
    print('点击:', (demos[0].get('txt') or '')[:60])
    pg.evaluate("(s) => { var b = document.querySelector(s); if (b) b.click(); }", SEL_BTN)
    pg.wait_for_timeout(1500)

    # 等地图 + 覆盖层就位。⚠️ 双通道等待（2026-09-20 实测教训）：
    #   只等 DOM 会**卡在边界上** —— 分析链实测约 90s 才渲染完工作台，
    #   而等待循环如果刚好在那一刻退出，就会误报"没渲染"。
    #   所以同时轮询磁盘上的 dashboard.json（服务端写、前端读，同一个事实）：
    #   一旦它落到 kind=analysis 且带 sim，就再多等 3s 让前端把这帧画出来。
    DASH = ROOT / 'public' / 'dashboard.json'
    got = False
    seen_kind = None
    acted = set()
    n_submit = 0
    for i in range(90):                                   # 最长 180s
        pg.wait_for_timeout(2000)
        n = pg.evaluate("document.querySelectorAll('.zr-simstage svg path').length")
        try:
            _d = json.loads(DASH.read_text(encoding='utf-8'))
            seen_kind = _d.get('kind')
            # 完整分析链要依次过：candidates → brands → input(投入) → analysis
            # 少任何一步都会停在中间（实测：只发一句话会停在「铺位未定」）。
            if _d.get('kind') == 'brands' and 'brands' not in acted:
                acted.add('brands')
                n_click = pg.evaluate(
                    "() => { var all = document.querySelectorAll('.brand-card[data-brand]');"
                    " for (var i = 0; i < all.length; i++) {"
                    "   if ((all[i].getAttribute('data-brand') || '').indexOf('蜜雪') >= 0)"
                    "     { all[i].click(); return '蜜雪'; } }"
                    " if (all.length) { all[0].click(); return 'first'; } return null; }")
                print('  → 点品牌卡:', n_click)
                pg.wait_for_timeout(2500)
            elif _d.get('kind') == 'input' and n_submit < 3:
                # ⚠️ 两件实测教训：
                #   ① 表单是前端 innerHTML 渲染的，dashboard.json 落到 input 之后
                #      DOM 还要几十~几百 ms 才出按钮 —— 只搜一次会扑空（实测 None）；
                #   ② 投入表单有**加盟费软下限**：低于门槛时第一次点只出警告，
                #      「再点一次『提交并继续』即可」→ 所以必须允许点第二次。
                #   ⇒ 允许多次点击（最多 3 次），每次重试找按钮。
                for _k in range(8):
                    # 表单为空时提交会被校验挡住（实测点 3 次都不动）→ 先补默认值。
                    pg.evaluate(
                        "() => { var ins = document.querySelectorAll('.zr-field input');"
                        " ins.forEach(function (el) { if (!el.value) {"
                        "   el.value = '20万';"
                        "   el.dispatchEvent(new Event('input', {bubbles: true})); } });"
                        " return ins.length; }")
                    n_click = pg.evaluate(
                        "() => { var b = Array.from(document.querySelectorAll('button'))"
                        " .find(x => (x.innerText || '').indexOf('提交') >= 0);"
                        " if (b) { b.click(); return (b.innerText||'').trim(); } return null; }")
                    if n_click:
                        n_submit += 1
                        print('  → 第 %d 次点「提交并继续」' % n_submit)
                        break
                    pg.wait_for_timeout(1200)
                if not n_click:
                    print('  ⚠️ 没找到「提交并继续」按钮（DOM 未就绪？）')
                pg.wait_for_timeout(3500)
            if _d.get('kind') == 'analysis' and isinstance(_d.get('sim'), dict):
                # 落一份快照：dashboard.json 会被后来的"新会话"清空，
                # 这里先固定住证据再检查（否则 §C 读到的是 clear）
                SNAP.write_text(json.dumps(_d, ensure_ascii=False), encoding='utf-8')
                pg.wait_for_timeout(3000)                 # 让前端渲染这一帧
                n = pg.evaluate("document.querySelectorAll('.zr-simstage svg path').length")
        except Exception:                                 # noqa: BLE001
            pass
        if n:
            got = True
            print('第 %d 轮（%.0fs）见到折线，path 数 = %d，dashboard.kind=%s'
                  % (i + 1, (i + 1) * 2, n, seen_kind))
            break
    if not got:
        print('★ 等待 180s 仍未见到覆盖层；最后一次看到的 dashboard.kind =', seen_kind)
    pg.wait_for_timeout(1500)

    print()
    print('=' * 70)
    print('§A 覆盖层结构')
    print('=' * 70)
    info = pg.evaluate("""(() => {
      const st = document.querySelector('.zr-simstage');
      const svg = st ? st.querySelector('svg') : null;
      if (!svg) return {has_stage: !!st, has_svg: false};
      const paths = Array.from(svg.querySelectorAll('path'));
      const anims = Array.from(svg.querySelectorAll('animateMotion'));
      const img = document.querySelector('.zr-map img');
      return {
        has_stage: true, has_svg: true,
        viewBox: svg.getAttribute('viewBox'),
        paths: paths.length,
        anims: anims.length,
        total_pts: paths.reduce((a,p) => a + (p.getAttribute('d')||'').split('L').length, 0),
        anim_dur: anims.length ? anims[0].getAttribute('dur') : null,
        anim_path_head: anims.length ? (anims[0].getAttribute('path')||'').slice(0,46) : null,
        img_w: img ? img.getBoundingClientRect().width : null,
        svg_w: svg.getBoundingClientRect().width,
        svg_h: svg.getBoundingClientRect().height,
        stage_h: st ? st.getBoundingClientRect().height : null,
        circles: svg.querySelectorAll('circle').length
      };
    })()""")
    print(json.dumps(info, ensure_ascii=False, indent=1))
    check('覆盖层容器 zr-simstage 存在', info.get('has_stage'))
    check('SVG 覆盖层已渲染', info.get('has_svg'))
    check('折线 path 已画出（≥3 条）', (info.get('paths') or 0) >= 3, info.get('paths'))
    check('小人 animateMotion 已挂上（与折线同数）',
          info.get('anims') == info.get('paths'), (info.get('anims'), info.get('paths')))
    check('animateMotion 的 path 是折线（M...L...）',
          bool(info.get('anim_path_head')) and 'L' in (info.get('anim_path_head') or ''),
          info.get('anim_path_head'))
    check('viewBox 与地图图幅同源（0 0 W W）',
          str(info.get('viewBox') or '').startswith('0 0 '), info.get('viewBox'))
    check('覆盖层与地图图**等宽等高**（没有错位/拉伸）',
          abs((info.get('svg_w') or 0) - (info.get('img_w') or 0)) < 1.5
          and abs((info.get('svg_h') or 0) - (info.get('img_w') or 0)) < 1.5,
          (info.get('img_w'), info.get('svg_w'), info.get('svg_h')))

    print()
    print('=' * 70)
    print('§B 图注与口径 chips')
    print('=' * 70)
    txt = pg.inner_text('#zl-right') if pg.query_selector('#zl-right') else ''
    chips = pg.evaluate("Array.from(document.querySelectorAll('#zl-right .zr-chip')).map(e=>e.innerText)")
    print('chips =', json.dumps(chips, ensure_ascii=False))
    check('图注写明「彩色轨迹 = 步行路网路径，小人沿真实街道走向本铺」',
          '步行路网路径' in txt)
    check('chips 报出真实轨迹条数（n/n 条真实街道）', any('条真实街道' in c for c in chips), chips)
    check('chips 报出最近客群的路网距离与绕行倍数',
          any(('m' in c and '绕行' in c) for c in chips), chips)
    check('画面标注仿真倍速（不糊弄）', any('仿真倍速' in c for c in chips), chips)
    check('选点/轨迹口径都写在图注里',
          '步行路网距离' in txt and 'direction/walking' in txt)
    check('说明点明"轨迹只用于可视化，不参与 D/P 计算"', '不参与 D/P 计算' in txt)

    print()
    print('=' * 70)
    print('§C 与模型口径一致（地图点 = 进 Huff 的点）')
    print('=' * 70)
    dash = json.loads((SNAP if SNAP.exists() else ROOT / 'public' / 'dashboard.json').read_text(encoding='utf-8'))
    sim = dash.get('sim') or {}
    check('dashboard.json 里带 sim', bool(sim))
    check('sim.ok = True', sim.get('ok') is True, sim.get('原因'))
    tg = sim.get('targets') or []
    check('sim 至少 5 个点且都有折线',
          len(tg) >= 5 and all(len(t.get('path_px') or []) > 1 for t in tg), len(tg))
    check('每个点的 road_m 都 ≤ 分析半径（与模型同一批点）',
          all(t['road_m'] <= (sim.get('meta') or {}).get('半径m', 500) for t in tg),
          [(t['name'], t['road_m']) for t in tg])
    check('绕行倍数逐点不同（不是常数近似）',
          len({t.get('ratio') for t in tg}) >= 4, [t.get('ratio') for t in tg])

    pg.screenshot(path=str(SHOTS / '21_sim_dashboard.png'), full_page=False)
    print()
    print('[截图]', SHOTS / '21_sim_dashboard.png')
    br.close()

print()
if FAIL:
    print('✗ %d 项未通过：' % len(FAIL))
    for f in FAIL:
        print('   ·', f)
    sys.exit(1)
print('✓ 仿真看板实机渲染：全部通过')
