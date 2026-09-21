# -*- coding: utf-8 -*-
"""live_ui_probe.py —— §2/§3/§5 的**实机**验证（Playwright + 真服务）
==========================================================================
⚠️ 本脚本**不在** `run_regression.py` 的门禁里（要起 Chainlit 服务、依赖真实会话数据，
   天然 flaky —— 项目纪律：这类只作信息性验证）。
   可复用的静态+纯逻辑断言版本在 `verify_ui.py`（那个进离线门禁）。
   两者关系：`verify_ui.py` 钉住"代码没有回退"，本脚本回答"在真浏览器里真的成立吗"。
   本项目历史上正是靠本脚本才发现 `scroller()` 选错元素（兜底层全程空转）。

它要回答只有真浏览器才能回答的问题：
  §2  点历史会话：是否**没有**中间覆盖层？聊天区是否**真的出现**历史消息？
      「查看更早」是否能补出更早的一批？
  §3  PDF 弹层打开后，弹层中心点的 `elementFromPoint` 是否命中弹层自身
      （即"没被别的东西挡住"）？它的 z-index 是否被抬到 3000？
  §5  在专家条上切换专家后，聊天列 `scrollTop` 是否**不变**（不跳回顶部）？
      ——并**先证明这次点击真的生效**（当前专家变了 / 新增了步骤），
      否则"scrollTop 不变"只能说明"什么都没发生"。
  §11 入口B 全链路（说地点 → 出候选铺源 → 选一家 → 四品类反推）。
  §12/§12b 候选卡片的房源性质标签 / 定位精度 / 投入表单的加盟费提示与软下限。
  §16 瑞幸一等公民：静态知识页是否同步、品牌卡是否真的能选到、
      投入表单提示是否说"明确不收加盟费"而不是"暂无公开口径"。
      ⚠️ §16 存在的理由：加盟费三态有**两处表面**（`agent_graph.py` 聊天提示 /
      `app_chainlit.py` 投入表单提示）。2026-09-18 就是这么抓到的 —— 静态断言
      §15 全绿，但 `app_chainlit.py` 里那段仍是老的两态 `if jf.get('fee'):`，
      瑞幸 fee=0 是 falsy → 表单上写「暂无公开加盟费口径」（假话）。
      **静态断言验不出"这句话在屏幕上不对"**，只有实机读 innerText 才能。
  §18 政策顾问：回答后「参考链接（原文出处）」块在真实 DOM 里是可点的 <a href>
      （确定性追加，不靠 LLM 复述）；模型审计师：样本量主数字 796（扩样可用）+
      引擎生效真相 83 并存。⚠️ 断言范围收进 .zl-chatcol —— 侧栏知识页里本来就有
      "83 家"，读 body.innerText 会假绿。

⚠️ 前置：**必须先重启服务**。Chainlit 默认不热重载 —— 服务跑着旧进程时，
   本脚本验到的是旧代码（§11 里那段"仍在跑旧进程"的判定就是为此加的）。

用法：
  1) 先起服务（Chainlit 必须在 3.12）：
     C:\\Python312\\python.exe -m chainlit run src/ui/app_chainlit.py --port 8502
  2) C:\\Python312\\python.exe src/analysis/live_ui_probe.py     ← 必须 3.12（Playwright 在这边）
输出：同目录 _live_ui_report.txt + 项目根 _ui_shots/*.png
"""
import io
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent          # 项目根（与其它验证脚本一致）
# ⚠️ 必须自己把 `src` 放进 sys.path：§16b 要 import 引擎（engine.brands）做跨表面比对。
#    2026-09-18 踩过：按文档用法直接跑（没设 PYTHONPATH）→
#    ModuleNotFoundError: No module named 'engine'，整轮探针中断。
sys.path.insert(0, str(ROOT / 'src'))
SHOTS = ROOT / '_ui_shots'
SHOTS.mkdir(exist_ok=True)
L, FAIL = [], []


def p(*a):
    s = ' '.join(str(x) for x in a)
    print(s)
    L.append(s)


def check(name, cond, detail=''):
    p(f'  {"PASS" if cond else "FAIL"}  {name}' + (f'  |  {detail}' if detail else ''))
    if not cond:
        FAIL.append(name)


def info(name, detail=''):
    p(f'  ---- {name}' + (f'  |  {detail}' if detail else ''))


JS_SCROLLER = """(() => {
    var all = document.querySelectorAll('.flex.flex-col.flex-grow.overflow-y-auto');
    if (!all.length) return null;
    var best = all[all.length - 1], bestOver = -1;
    for (var i = 0; i < all.length; i++) {
        var over = all[i].scrollHeight - all[i].clientHeight;
        if (over > bestOver) { bestOver = over; best = all[i]; }
    }
    return best;
})()"""


def main():
    from playwright.sync_api import sync_playwright

    URL = 'http://127.0.0.1:8502'
    with sync_playwright() as pw:
        # 与 `report_pdf.py` 一致：优先系统 Chrome，再退到自带的完整 chromium。
        # ⚠️ **不能**用默认的 `launch()`：它走 `chromium_headless_shell`，而这台机器
        # 只装了完整 chromium（chromium-1223/chrome-win64），headless_shell 没下载
        # → 直接 "Executable doesn't exist"。项目自己生成 PDF 时也是这么绕的。
        br = None
        for kw in ({'headless': True, 'channel': 'chrome'},
                   {'headless': True,
                    'executable_path': pw.chromium.executable_path},
                   {'headless': True}):
            try:
                br = pw.chromium.launch(**kw)
                info('浏览器启动方式', json.dumps(kw, ensure_ascii=False))
                break
            except Exception as e:
                info('启动失败，换下一种', f'{list(kw)} → {str(e)[:70]}')
        if br is None:
            check('Playwright 浏览器可启动（前置条件）', False, '三种方式都失败')
            return
        pg = br.new_page(viewport={'width': 1600, 'height': 950})
        pg.on('console', lambda m: None)
        p(f'打开 {URL}')
        pg.goto(URL, wait_until='load', timeout=60000)
        pg.wait_for_timeout(6000)          # 等首屏 + sidebar.json 轮询（2.5s 一轮）

        # ---------------------------------------------------------- 准备
        rows = pg.query_selector_all('#zl-hist .zl-hist-info[data-open]')
        info('历史会话条数', str(len(rows)))
        if not rows:
            check('历史会话列表已渲染（前置条件）', False, '没有可点的历史项，后面对照无从谈起')
            pg.screenshot(path=str(SHOTS / '00_no_history.png'))
            br.close()
            return
        # 选消息最多的那条（才能覆盖"最近 N 条 + 查看更早"）
        pg.screenshot(path=str(SHOTS / '01_initial.png'))

        # ------------------------- 欢迎语标题花纹（诉求⑤）—— 只有实机能验
        p('')
        p('=== 欢迎语标题两侧花纹（真浏览器里读伪元素，静态断言验不了） ===')
        # 静态断言只能证明"源码里有这几条 CSS"。花纹到底贴上去没有、贴对了没有、
        # 有没有把标题撑变形 —— 只有真浏览器算得出来。
        # ⚠️ 必须用 getComputedStyle(el, '::before')，不能用 querySelector：
        #    伪元素不在 DOM 里，选择器查不到，只会得到 null。
        # 新会话的欢迎语要等 websocket 建连后才渲染，先等到 h1 出现再断言。
        for _ in range(15):
            if pg.query_selector(
                    '[class*="message-content"] h1,[class*="Markdown"] h1,[class*="markdown"] h1'):
                break
            pg.wait_for_timeout(1000)
        hn = pg.evaluate("""(() => {
          const h = document.querySelector(
            '[class*="message-content"] h1,[class*="Markdown"] h1,[class*="markdown"] h1');
          if (!h) return {found: false};
          const pre = getComputedStyle(h, '::before');
          const post = getComputedStyle(h, '::after');
          const r = h.getBoundingClientRect();
          return {
            found: true,
            text: (h.textContent || '').trim(),
            preImg: pre.backgroundImage || '',
            postImg: post.backgroundImage || '',
            preContent: pre.content,
            postContent: post.content,
            preW: pre.width, postW: post.width,
            preH: pre.height, postH: post.height,
            preMarginRight: pre.marginRight,
            postMarginLeft: post.marginLeft,
            h1Left: Math.round(r.left), h1Top: Math.round(r.top),
            h1W: Math.round(r.width), h1H: Math.round(r.height)
          };
        })()""")
        check('欢迎语 h1 在实机里存在', bool(hn.get('found')), str(hn)[:120])
        if hn.get('found'):
            info('h1 文本', str(hn.get('text'))[:40])
            info('h1 盒子（left/top/宽/高）',
                 f"{hn.get('h1Left')}/{hn.get('h1Top')}/{hn.get('h1W')}x{hn.get('h1H')}")
            check('h1 的 ::before 有内容（花纹真的贴上了）',
                  hn.get('preContent') not in ('none', '', None), str(hn.get('preContent')))
            check('h1 的 ::after 有内容',
                  hn.get('postContent') not in ('none', '', None), str(hn.get('postContent')))
            check('::before 的背景是内联 SVG（data-URI 真的被浏览器吃下了）',
                  'data:image/svg' in hn.get('preImg', ''),
                  str(hn.get('preImg'))[:80])
            check('::after 的背景也是内联 SVG',
                  'data:image/svg' in hn.get('postImg', ''))
            check('左右花纹是同一方案（严格镜像成对，不是两个不同图案）',
                  hn.get('preImg') == hn.get('postImg'))
            check('花纹左右各归一边（before 右留白 / after 左留白，不能都贴标题）',
                  float(hn.get('preMarginRight', '0px').replace('px', '') or 0) > 0
                  and float(hn.get('postMarginLeft', '0px').replace('px', '') or 0) > 0,
                  f"before mr={hn.get('preMarginRight')} after ml={hn.get('postMarginLeft')}")
            check('花纹尺寸非零（CSS 生效，不是塌成 0 的隐形元素）',
                  float(hn.get('preW', '0px').replace('px', '') or 0) > 0
                  and float(hn.get('preH', '0px').replace('px', '') or 0) > 0,
                  f"{hn.get('preW')}x{hn.get('preH')}")
            # 不跳版：44px 标题 + line-height 1.25 ≈ 55px 一行。
            # 花纹是 inline-block 且只有 34px，贴上去不该把 h1 撑到多行。
            check('贴花纹没把标题撑成多行（h1 高度仍是一行量级，不跳版）',
                  0 < (hn.get('h1H') or 0) <= 80, str(hn.get('h1H')))
            # ---- 渐变「看得出来」（2026-09-17 欧文反馈"渐变太不明显"）------------
            # 静态断言只能证明"色标写对了、fit-content 写了"，那是必要条件不是充分条件：
            # 到底看不看得出是**视觉**问题，只有量像素才算数。
            # 做法：截 h1 元素图 → 跳过左右花纹（各 48px）→ 沿 x 逐列取最亮像素
            #      （深色主题下文字比底亮）→ 看文字像素的**明度极差**。
            # 旧版为什么看不出：极差只有 ~26，且背景摊在整行 750px 上被稀释。
            check('h1 已收缩到内容宽（fit-content 生效）：盒子该贴住"花纹+文字"，'
                  '不该撑满整行 —— 撑满时色阶摊在 750px 上，文字只截到中间一小段',
                  (hn.get('h1W') or 9999) <= 460,
                  f"h1W={hn.get('h1W')}（撑满整行时约 750）")
            try:
                from PIL import Image
                _l, _t = hn.get('h1Left'), hn.get('h1Top')
                _w, _hh = hn.get('h1W') or 0, hn.get('h1H') or 0
                _x0, _x1 = _l + 48, _l + _w - 48           # 跳过左右花纹（34+14）
                if _w > 140 and _hh > 20 and _x1 > _x0:
                    _shot = pg.screenshot(clip={'x': _x0, 'y': _t,
                                                'width': _x1 - _x0, 'height': _hh})
                    _im = Image.open(io.BytesIO(_shot)).convert('RGB')

                    def _lu(_p):
                        return (_p[0] * .299 + _p[1] * .587 + _p[2] * .114) / 255 * 100

                    # 分离文字像素用**色相**判据，不用亮度 —— 这点很关键：
                    # 文字带 drop-shadow 金色光晕，光晕把背景抬到 ~59，而渐变**暗部
                    # 文字本身只有 ~52**，两者挨得很近。若按"亮度 > 背景"筛列，最暗那几列
                    # （恰恰是"渐变到底明不明显"的证据）会被当成背景扔掉，极差被系统性
                    # 低估 —— 第一版实测 25.4 / 设计值 ~47，就是这么来的。
                    # 金色像素 R-B ≈ 175，冷墨绿背景 R-B ≈ -28，一刀切得干净。
                    _cols = []
                    for _cx in range(_im.width):
                        _mx = -999.0
                        for _cy in range(_im.height):
                            _p = _im.getpixel((_cx, _cy))
                            if _p[0] - _p[2] > 60:                 # 暖色 = 文字笔画
                                _v = _lu(_p)
                                if _v > _mx:
                                    _mx = _v
                        if _mx > -999:
                            _cols.append(_mx)
                    _txt = _cols
                    _span = (max(_txt) - min(_txt)) if _txt else 0.0
                    _seg = max(1, len(_txt) // 10) if _txt else 1
                    _trend = [sum(_txt[i:i + _seg]) / len(_txt[i:i + _seg])
                              for i in range(0, len(_txt), _seg)] if _txt else []
                    info('文字明度沿 x 走势（左→右 10 等分，0=黑 100=白）',
                         ' '.join(f'{v:.0f}' for v in _trend))
                    check('h1 文字上真有渐变：沿 x 采样文字像素的明度极差 ≥ 28'
                          '（"看不出渐变"的本质就是这个数太小；旧版 ~26 会被拦下）',
                          _span >= 28,
                          f'极差 {_span:.1f}（最暗字面 {min(_txt) if _txt else 0:.1f} / '
                          f'最亮字面 {max(_txt) if _txt else 0:.1f}），采到 {len(_txt)} 列文字像素')
                else:
                    check('h1 尺寸够做像素采样', False, f'{_w}x{_hh}')
            except Exception as _e:
                check('渐变像素采样可执行（依赖 PIL）', False, f'{type(_e).__name__}: {_e}')
        pg.screenshot(path=str(SHOTS / '10_welcome_motif.png'))

        # ------------------------------------------- §2 点击历史：一步到位
        p('')
        p('=== §2 点历史会话：无中间页 + 回放 ===')
        # ⚠️ 必须**挑一条消息多的会话**，不能写死 rows[0]。
        #    侧栏不暴露消息条数，所以逐个点、试到出现「查看更早」为止。
        #    这条修正来自实机：§11 会新开若干短会话，它们排在最上面 →
        #    写死 rows[0] 就会去点一条 2 条消息的会话，然后必然报"没有查看更早"，
        #    看起来像分页坏了，其实只是选错了样本。
        ids = [r.get_attribute('data-open') for r in rows]
        info('历史会话 id', str(ids))
        pg.screenshot(path=str(SHOTS / '01_initial.png'))
        tried, picked, ov_open = [], None, False
        for cid in ids[:4]:
            h = pg.query_selector('.zl-hist-info[data-open="%s"]' % cid)
            if not h:
                continue
            h.click()
            pg.wait_for_timeout(9000)      # 回放 + 工作台重渲（含 PDF 复用/生成）
            tried.append(cid)
            ov_open = pg.evaluate(
                "!!(document.getElementById('zl-page-ov') && "
                "document.getElementById('zl-page-ov').classList.contains('open'))")
            if '查看更早' in pg.inner_text('body'):
                picked = cid
                break
        info('试过的会话', str(tried))
        info('选中的会话（消息多到需要分页）', str(picked))
        check('**没有**中间覆盖层（#zl-page-ov 未 open）', not ov_open,
              '改前点历史项会先弹只读中间页，要再点一次「继续对话」')

        body_txt = pg.inner_text('body')
        check('聊天区出现"已切换到历史会话"提示',
              '已切换到历史会话' in body_txt)
        check('聊天区出现回放批次说明（最近 N 条）',
              '回放' in body_txt and '最近' in body_txt)
        n_user = pg.evaluate(
            "document.querySelectorAll('[data-step-type=\"user\"], .user-message, "
            "[class*=\"user\"]').length")
        info('疑似用户气泡节点数', str(n_user))
        # Chainlit 2.11 把 type='user_message' 渲染成带 user 语义的步骤，换几种选择器兜
        _has_replay_user = pg.evaluate("""(() => {
            var t = document.body.innerText || '';
            return t.includes('已切换到历史会话');
        })()""")
        check('切换提示已渲染（回放通道建立）', _has_replay_user)
        check('至少一条会话触发「查看更早」（消息数 > REPLAY_TAIL）',
              picked is not None,
              f'试过 {len(tried)} 条；都没有说明回放分页真的坏了，而不是样本太短')
        pg.screenshot(path=str(SHOTS / '02_history_replayed.png'), full_page=False)

        # ------------------------------------------- §2 查看更早
        p('')
        p('=== §2 查看更早（补发更早一批）===')
        btn = None
        for cand in pg.query_selector_all('button'):
            try:
                if '查看更早' in (cand.inner_text() or ''):
                    btn = cand
                    break
            except Exception:
                continue
        if btn:
            btn.click()
            pg.wait_for_timeout(4000)
            t2 = pg.inner_text('body')
            check('补发出了「更早的记录」批次说明', '更早的记录' in t2)
            check('补发后仍有/已无「查看更早」（进度推进）',
                  ('查看更早' in t2) or ('已显示该会话全部' in t2),
                  '17 条 = 8 + 8 + 1，第二轮后应还剩 1 条')
            pg.screenshot(path=str(SHOTS / '03_history_earlier.png'))
        else:
            check('找到「查看更早」按钮', False, '按钮未渲染 → 无法验证补发')

        # ------------------------------------------- §5 切专家不跳顶
        p('')
        p('=== §5 切换专家：聊天列 scrollTop 不跳回顶部 ===')
        scrolled = pg.evaluate("""(() => {
            var c = %s;
            if (!c) return null;
            c.scrollTop = Math.max(0, c.scrollHeight - c.clientHeight - 120);
            return { top: c.scrollTop, max: c.scrollHeight - c.clientHeight };
        })()""" % JS_SCROLLER)
        info('滚动列状态', json.dumps(scrolled, ensure_ascii=False))
        if scrolled and scrolled['top'] > 8:
            # 点专家条上的某个**非当前**专家（静默指令 ##专家:<id>##，正是触发跳顶的那条路径）
            tg = pg.query_selector('#xb-toggle')
            if tg and not any(r.is_visible() for r in pg.query_selector_all('#zl-xbar .xb-row')):
                tg.click()
                pg.wait_for_timeout(600)
            ex = None
            for cand in pg.query_selector_all('#zl-xbar .xb-row[data-xid]'):
                try:
                    if cand.is_visible() and 'cur' not in (cand.get_attribute('class') or ''):
                        ex = cand
                        break
                except Exception:
                    continue
            if ex:
                _target = ex.get_attribute('data-xid')
                info('切换到的专家', _target)
                cur_before = pg.evaluate(
                    "(() => { var e=document.querySelector('#zl-xbar .xb-row.cur[data-xid]');"
                    " return e ? e.getAttribute('data-xid') : null; })()")
                steps_before = pg.evaluate("document.querySelectorAll('.step').length")
                top_before = pg.evaluate("(() => { var c = %s; return c ? c.scrollTop : -1; })()"
                                         % JS_SCROLLER)
                ex.click()
                pg.wait_for_timeout(4000)      # 轮询 2.5s 一轮，要等 syncExperts 回填
                top_after = pg.evaluate("(() => { var c = %s; return c ? c.scrollTop : -1; })()"
                                        % JS_SCROLLER)
                steps_after = pg.evaluate("document.querySelectorAll('.step').length")
                cur_after = pg.evaluate(
                    "(() => { var e=document.querySelector('#zl-xbar .xb-row.cur[data-xid]');"
                    " return e ? e.getAttribute('data-xid') : null; })()")
                info('当前专家', f'{cur_before} → {cur_after}')
                info('步骤节点数', f'{steps_before} → {steps_after}')
                # 前置条件：必须先证明"这次点击真的发出去了静默指令"，
                # 否则 scrollTop 不变只能说明"什么都没发生"，不能证明"没跳顶"。
                check('点击确实触发了切换（当前专家变了，或新增了步骤）',
                      (cur_after != cur_before and cur_after == _target)
                      or steps_after > steps_before,
                      f'cur {cur_before}→{cur_after}，steps {steps_before}→{steps_after}')
                check('切专家后 scrollTop 未被拉回 0（不跳顶）',
                      top_after > 8, f'{top_before} → {top_after}')
                check('scrollTop 基本不变（±8px 容差）',
                      abs(top_after - top_before) <= 8, f'{top_before} → {top_after}')
                pg.screenshot(path=str(SHOTS / '04_expert_switch_scroll.png'))
            else:
                info('专家条上没找到可点元素，跳过 §5 实机项（静态断言已覆盖）')
        else:
            info('聊天列内容不足一屏，无法验证滚动（历史会话消息较少）')

        # ------------------------------------------- §3 PDF 不被遮挡
        p('')
        p('=== §3 PDF 弹层是否在最上层、无遮挡 ===')
        # 回放/重渲后应有一条带 PDF 附件的消息
        _pdf_opened = False
        for sel in ('iframe[src*="pdf"]', 'embed[type="application/pdf"]',
                    '[class*="pdf"]', 'a[href*=".pdf"]'):
            els = [e for e in pg.query_selector_all(sel) if e.is_visible()]
            if els:
                info('找到 PDF 相关元素', f'{sel} × {len(els)}')
                try:
                    els[0].click()
                    pg.wait_for_timeout(3000)
                    _pdf_opened = True
                    break
                except Exception as e:
                    info('点击失败', str(e)[:80])
        if _pdf_opened:
            probe = pg.evaluate("""(() => {
                var ds = [].slice.call(document.querySelectorAll('[role="dialog"]'));
                var vis = ds.filter(function(d){ var s=getComputedStyle(d);
                    return s.display!=='none' && s.visibility!=='hidden'; });
                if (!vis.length) return { n: 0 };
                var d = vis[vis.length-1];
                var r = d.getBoundingClientRect();
                var cx = Math.round(r.left + r.width/2), cy = Math.round(r.top + r.height/2);
                var hit = document.elementFromPoint(cx, cy);
                return { n: vis.length, z: getComputedStyle(d).zIndex,
                         rect: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)],
                         hitInDialog: !!(hit && (d === hit || d.contains(hit))),
                         hitTag: hit ? (hit.tagName + '.' + (hit.className||'').toString().slice(0,40)) : null };
            })()""")
            info('弹层探测', json.dumps(probe, ensure_ascii=False))
            check('PDF 弹层已打开（存在可见 [role="dialog"]）', probe.get('n', 0) > 0)
            check('弹层 z-index 被抬到 3000（覆盖项目内所有浮层 79~2050）',
                  str(probe.get('z')) == '3000', f"z={probe.get('z')}")
            check('弹层中心点 elementFromPoint 命中弹层自身（= 无遮挡）',
                  bool(probe.get('hitInDialog')),
                  f"命中 {probe.get('hitTag')}")
            pg.screenshot(path=str(SHOTS / '05_pdf_top.png'))
        else:
            info('本次会话没有可点的 PDF 元素，PDF 实机项未验（静态断言已覆盖 CSS+z-index+raisePdfModal）')

        # ------------------------------- §11 入口B 全链路（2026-09-17 新增）
        # 这是**只有实机能回答**的一问：静态断言能证明"代码接对了"，
        # 但证明不了"用户真的说一句『我想在杭州滨江开店』时，屏幕上真的会
        # 冒出十几家带租金/面积的铺子、点一家真的会出四品类反推"。
        # 独立会话验证：先重新加载（拿到全新 session），再走完整链路。
        p('')
        p('=== §11 入口B 全链路：说地点 -> 出候选 -> 选一家 -> 四品类反推 ===')
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
                except Exception:
                    continue
            return None

        sel_used = _send('我想在杭州滨江开店')
        info('composer 选择器', str(sel_used))
        check('能定位并提交输入框（前置条件）', sel_used is not None,
              'Chainlit composer 的 selector 变了就要同步这里')
        if sel_used:
            n_cand, cols, tags = 0, None, {}
            for _ in range(28):        # 58 多页并发 + 详情页补全，最坏 ~45s
                pg.wait_for_timeout(2000)
                n_cand = pg.evaluate(
                    "document.querySelectorAll('.cand-card[data-choose]').length")
                if n_cand:
                    break
            info('候选卡片数', str(n_cand))
            check('说一句"想在滨江开店"就直接出候选铺源（不是反问品类）',
                  n_cand > 0, '改造前会被反问"想开什么品类"或掉进闲聊')
            if not n_cand:
                # ⚠️ "服务端还在跑旧代码"和"链路真的坏了"是两件事，必须分开说。
                #    Chainlit **默认不热重载**，改完代码不重启就会拿到旧行为 ——
                #    实机踩到过：回复里赫然是改造前的"想开什么品类"，
                #    而图逻辑本身是好的（`verify_place_first` §1/§3 已覆盖）。
                #    混为一谈会让人去改一个没坏的模块。
                _bt = pg.inner_text('body')
                stale = ('想开什么品类' in _bt) or ('补充以下信息' in _bt)
                info('服务端返回的追问', '想开什么品类（改造前写法）' if stale else '（未见旧文案）')
                if stale:
                    info('⚠️ 判定', '服务端**仍在跑旧进程**（Chainlit 默认不热重载）。'
                                    '重启服务后再跑本脚本才验得了 §11 —— 这不是链路缺陷。')
                else:
                    info('判定', '回复里没有"想开什么品类"，需看截图/正文判断是真失败还是别的分支')
                pg.screenshot(path=str(SHOTS / '06b_place_first_stale.png'))
            check('候选数 >= 12（58 实测条目上限，目标 15）', n_cand >= 12, f'实际 {n_cand}')
            if n_cand:
                cols = pg.evaluate("""(() => {
                    var g = document.querySelector('#zl-right .cand-grid');
                    if (!g) return null;
                    var cs = getComputedStyle(g).gridTemplateColumns || '';
                    var parts = cs.split(' ').filter(function(x){ return x && x !== 'none'; });
                    return { raw: cs.slice(0, 90), w: g.clientWidth,
                             n: parts.length, col: parseFloat(parts[0]) || 0,
                             overflow: g.scrollWidth - g.clientWidth };
                })()""")
                info('候选网格列', json.dumps(cols, ensure_ascii=False))
                # ⚠️ 判据不是"列数 >= 2"。实机量到 `#zl-right` 只有 **421px** 宽，
                #    而网格是 `repeat(auto-fill, minmax(280px,1fr))` → 只能排 1 列。
                #    这是**正确**行为（280 以下是挤），原先写"必须 >=2 列"是我想当然。
                #    真正该守的是：没有列被压到读不清、也没有横向溢出。
                check('候选网格列宽合理（未被压到 <240px）且不横向溢出',
                      bool(cols) and cols.get('col', 0) >= 240
                      and cols.get('overflow', 0) <= 4,
                      f"列数 {cols and cols.get('n')} / 列宽 {cols and cols.get('col')}px / "
                      f"溢出 {cols and cols.get('overflow')}px / 容器 {cols and cols.get('w')}px")
                tags = pg.evaluate("""(() => {
                    var cs = document.querySelectorAll('.cand-card[data-choose]');
                    var warn = 0, mute = 0, none = 0;
                    cs.forEach(function (c) {
                        if (c.querySelector('.zl-tag.warn')) warn++;
                        else if (c.querySelector('.zl-tag.mute')) mute++;
                        else none++;
                    });
                    return { total: cs.length, derived: warn, unavailable: mute, plain: none };
                })()""")
                info('三态标签分布（实测/推算/未标）', json.dumps(tags, ensure_ascii=False))
                # 这一条**不是**要求"必须有推算值"，而是要求"标了推算的卡片
                # 上面真的能看见『推算』两个字" —— 后端算了口径却不显示，
                # 用户就会把推算值当实测值读。
                check('三态标签之和 == 卡片数（没有卡片被漏标）',
                      tags.get('total') == tags.get('derived', 0)
                      + tags.get('unavailable', 0) + tags.get('plain', 0),
                      json.dumps(tags, ensure_ascii=False))
                pg.screenshot(path=str(SHOTS / '06_place_first_candidates.png'))

                # ---- §12 房源性质标签 + 定位精度（2026-09-17 新增，诉求②③）
                # ⚠️ 必须**在点卡片之前**跑：点完右栏就换成四品类反推、候选卡片
                #    消失 —— 第一版把它挂在链路末尾，结果只数到 0 张（实机抓到的）。
                # 静态断言只能证明"代码里写了 dl-tr/dl-rt"，证明不了屏幕上真的
                # 渲染出来了、且没跟三态标签撞 class。
                p('')
                p('=== §12 候选卡片：房源性质标签 / 定位精度 / 与三态标签不撞车 ===')
                deal = pg.evaluate("""(() => {
                    var cs = document.querySelectorAll('.cand-card[data-choose]');
                    var tr = 0, rt = 0, other = 0, loc = 0, clash = 0;
                    cs.forEach(function (c) {
                        var nm = c.querySelector('.cand-name');
                        var ts = nm ? nm.querySelectorAll('.zl-tag') : [];
                        var k = null;
                        for (var i = 0; i < ts.length; i++) {
                            var cl = ts[i].className;
                            if (cl.indexOf('dl-tr') >= 0) {
                                k = 'tr';
                                if (cl.indexOf('warn') >= 0 || cl.indexOf('mute') >= 0) clash++;
                            } else if (cl.indexOf('dl-rt') >= 0) {
                                k = 'rt';
                                if (cl.indexOf('warn') >= 0 || cl.indexOf('mute') >= 0) clash++;
                            }
                        }
                        if (k === 'tr') tr++; else if (k === 'rt') rt++; else other++;
                        if ((c.innerText || '').indexOf('定位精度') >= 0) loc++;
                    });
                    return { total: cs.length, transfer: tr, rent: rt,
                             no_deal_tag: other, with_loc: loc, clash: clash };
                })()""")
                info('房源性质标签分布', json.dumps(deal, ensure_ascii=False))
                check('房源性质标签没复用三态 class（warn/mute）',
                      deal['clash'] == 0,
                      '撞了会把转让铺误统计成"推算值"（§11 三态探针数的是 .zl-tag.warn）')
                # ⚠️ 这一条才是能抓住"判不出的被冒充成房东招租"的断言：
                #    单看"每张卡都有标签"永远为真 —— 判不出的那些正好被前端
                #    默认成了"房东招租"（实机就出现过 15 家里只报 3+1）。
                #    所以必须**跟聊天区给的构成对账**。
                body = pg.inner_text('body')
                m_rt = re.search(r'(\d+)\s*家房东招租', body)
                m_tf = re.search(r'(\d+)\s*家转让', body)
                info('聊天区给的房源性质构成',
                     f"房东招租={m_rt.group(1) if m_rt else '?'} / "
                     f"转让={m_tf.group(1) if m_tf else '?'} / "
                     f"卡片上没打性质标签的={deal['no_deal_tag']}")
                check('卡片"房东招租"数 == 聊天区说的数（判不出的不许冒充房东招租）',
                      bool(m_rt) and int(m_rt.group(1)) == deal['rent'],
                      f"聊天区 {m_rt and m_rt.group(1)} vs 卡片 {deal['rent']}")
                # ⚠️ **数据条件 ≠ 代码缺陷**：本批一张转让铺都没有时，聊天区**不会**报"转让"，
                #    此时 `m_tf` 为 None 是**正确行为**，判 FAIL 就是假红。2026-09-18 实测：
                #    同一天两轮，首轮 15 张卡里恰有转让铺 → 有这句话；次轮 `transfer=0` → 没有这句话。
                #    （58 每次给回的房源不同 → 这条天然 flaky。）
                #    但反向仍然是真错："卡片 0 家、聊天区却说有 N 家"必须拦。
                if deal['transfer'] == 0:
                    check('卡片"转让"数 == 聊天区说的数（本批 0 家转让 → 聊天区不提"转让"属正确行为）',
                          m_tf is None or int(m_tf.group(1)) == 0,
                          f"聊天区 {m_tf and m_tf.group(1)} vs 卡片 0")
                else:
                    check('卡片"转让"数 == 聊天区说的数',
                          bool(m_tf) and int(m_tf.group(1)) == deal['transfer'],
                          f"聊天区 {m_tf and m_tf.group(1)} vs 卡片 {deal['transfer']}")
                info('带"定位精度"提示的卡片数',
                     f"{deal['with_loc']} / {deal['total']}")
                pg.screenshot(path=str(SHOTS / '08_cand_deal_tags.png'))

                pg.query_selector('.cand-card[data-choose]').click()
                n_cat = 0
                for _ in range(45):
                    pg.wait_for_timeout(2000)
                    n_cat = pg.evaluate(
                        "document.querySelectorAll('.cat-card[data-cat]').length")
                    if n_cat:
                        break
                info('四品类卡片数', str(n_cat))
                check('选中一家后**自动**出四品类反推（四个都出齐）', n_cat == 4,
                      f'实际 {n_cat} 个 —— 入口B 的关键动作是"先给铺子、再反推"，'
                      '不是回头问"你想开什么品类"')
                if n_cat:
                    right_txt = pg.inner_text('#zl-right')
                    info('右栏首 160 字', right_txt[:160].replace('\n', ' / '))
                    check('四品类卡片点得出"不可比"或口径说明（跨品类结论的诚实底线）',
                          ('不可比' in right_txt) or ('口径' in right_txt)
                          or ('经验值' in right_txt),
                          '竞争分/总分跨品类不可比，必须对用户说清')
                    pg.screenshot(path=str(SHOTS / '07_place_first_reverse.png'))

        # ---- §12b 加盟费提示行 + 软下限（诉求④⑦）
        p('')
        p('--- §12b 前期投入表单：加盟费提示 / 低于门槛要二次确认 ---')
        ncat = pg.evaluate("document.querySelectorAll('.cat-card[data-cat]').length")
        if not ncat:
            info('跳过', '当前会话没走到四品类反推，§12b 未验')
        else:
            # 优先点「奶茶」：只有奶茶走 collect_brand，才验得到加盟费下限；
            # 点第一个卡片常落到甜品/早餐（无品牌 -> 没有 floor 节点 -> 跳过）。
            clicked = pg.evaluate("""(() => {
                var m = document.querySelector('.cat-card[data-cat="奶茶"]');
                if (!m) m = document.querySelector('.cat-card[data-cat]');
                if (!m) return null;
                m.click();
                return m.getAttribute('data-cat');
            })()""")
            info('点开的品类', str(clicked))
            nb = 0
            for _ in range(16):
                pg.wait_for_timeout(1500)
                nb = pg.evaluate("document.querySelectorAll('.brand-card[data-brand]').length")
                if nb:
                    break
            info('品牌卡片数', str(nb))
            if nb:
                b = pg.evaluate("""(() => {
                    var all = document.querySelectorAll('.brand-card[data-brand]');
                    var m = null;
                    for (var i = 0; i < all.length; i++) {
                        if ((all[i].getAttribute('data-brand') || '').indexOf('蜜雪') >= 0) { m = all[i]; break; }
                    }
                    if (!m) m = all[0];
                    if (!m) return null;
                    m.click();
                    return m.getAttribute('data-brand');
                })()""")
                info('点开的品牌', str(b))
            nf = 0
            for _ in range(24):
                pg.wait_for_timeout(1500)
                nf = pg.evaluate("document.querySelectorAll('#zl-input-form input[data-key]').length")
                if nf:
                    break
            info('投入表单字段数', str(nf))
            if not nf:
                info('跳过', '没等到投入表单（该品类可能不走投入环节），§12b 未验')
            else:
                note = pg.evaluate(
                    "(() => { var e=document.querySelector('#zl-input-form .zr-note');"
                    "return e ? e.innerText : ''; })()")
                fl = pg.evaluate(
                    "(() => { var e=document.querySelector('#zl-input-form .zr-floor');"
                    "return e ? {floor:e.getAttribute('data-floor'),"
                    "brand:e.getAttribute('data-brand')} : null; })()")
                info('口径提示行', str(note)[:180].replace('\n', ' / '))
                info('门限节点', json.dumps(fl, ensure_ascii=False))
                check('投入表单带加盟费提示行（不用用户自己去查）',
                      bool(note) and ('加盟费' in note),
                      '诉求④：填投入时边上要提示该品牌加盟费')
                inp = pg.query_selector('#zl-input-form input[data-key="investment"]')
                if not inp or not fl:
                    info('跳过', '没有 investment 输入框或 floor 节点，软下限未验')
                else:
                    inp.fill('1')          # 1 万 —— 必然低于任何品牌的加盟费
                    pg.wait_for_timeout(200)
                    pg.click('#zl-input-form button[type="submit"]')
                    pg.wait_for_timeout(900)
                    st = pg.evaluate(
                        "(() => { var e=document.querySelector('#zl-input-form .zr-floor');"
                        "return e ? {cls:e.className, acked:e.getAttribute('data-acked'),"
                        "txt:(e.innerText||'').slice(0,130)} : null; })()")
                    info('第一次提交后门限节点', json.dumps(st, ensure_ascii=False))
                    check('填 1 万（低于加盟费）第一次提交被拦住并标红',
                          bool(st) and 'warn' in (st.get('cls') or '')
                          and st.get('acked') == '1',
                          '⑦ 是"显示后放行"，所以提示必须**看得见**')
                    pg.screenshot(path=str(SHOTS / '09_invest_floor_warn.png'))
                    # 再点一次 -> 必须真的放行（软下限的本意）
                    if pg.evaluate("!!document.querySelector('#zl-input-form')"):
                        pg.click('#zl-input-form button[type="submit"]')
                        gone = False
                        for _ in range(8):
                            pg.wait_for_timeout(1000)
                            if '投入1万' in pg.inner_text('body'):
                                gone = True
                                break
                        check('再点一次即放行（软下限，不硬拦）', gone,
                              '⑦ 原话"可以显示后放行"——第二次提交必须真的发出去')
                    else:
                        info('第一次提交后表单已消失', '说明没有拦住——若上面那条 PASS 则矛盾，需查')

        # ---- §16 瑞幸一等公民（2026-09-18 新增）------------------------------
        # 背景：本轮把瑞幸做成与蜜雪/古茗同级的一等公民，并修了「0 加盟费被
        #       当成查不到」的两态 bug。关键点：这个 bug 有**两处表面**——
        #       `agent_graph.py`（聊天提示）与 `app_chainlit.py`（投入表单提示）。
        #       改完 A 面忘了 B 面是本项目高发错（知识库两处表面同源）。
        #       静态断言只能证明"代码里写了三态"，证明不了"用户屏幕上真的看得见
        #       且说的是人话"——这正是本节要回答的、只有真浏览器能回答的问题。
        p('')
        p('=== §16 瑞幸一等公民：知识页同步 / 品牌卡可选 / 三态文案（实机）===')

        # 16a 知识页 —— KB_THEORY 是知识库的**第二个表面**（第一个是 knowledge.py 语料）
        kb_hit = pg.evaluate(
            "(() => { var b=document.querySelector('[data-cmd=\"kb_theory\"]');"
            " if (!b) return 'no-btn'; b.click(); return 'clicked'; })()")
        info('知识库入口点击', str(kb_hit))
        pg.wait_for_timeout(1200)
        kb = pg.evaluate("""(() => {
            var ov = document.getElementById('zl-page-ov');
            var bd = document.getElementById('zl-pg-body');
            var rows = [];
            if (bd) {
                bd.querySelectorAll('table.zl-kb-tb tr').forEach(function (tr) {
                    var t = (tr.innerText || '').replace(/\\s+/g, ' ').trim();
                    if (t.indexOf('瑞幸') >= 0) rows.push(t);
                });
            }
            return { open: !!(ov && ov.classList.contains('open')),
                     txt: bd ? (bd.innerText || '') : '', luckin_rows: rows };
        })()""")
        info('知识页是否打开', str(kb.get('open')))
        info('命中「瑞幸」的表格行', json.dumps(kb.get('luckin_rows'), ensure_ascii=False))
        check('知识库·选址打分依据页能打开（前置条件）', bool(kb.get('open')))
        # ⚠️ 必须在分支**外**先落地：16b 要拿这张表的标定值去对卡片上的百分比（跨表面一致性），
        #    若只在 `if kb.get('open')` 里赋值，知识页一开不起来 16b 就 NameError。
        krows = kb.get('luckin_rows') or []
        if kb.get('open'):
            kt = kb.get('txt') or ''
            krows = kb.get('luckin_rows') or []
            check('静态知识页写了瑞幸（第二个表面同步了）', '瑞幸' in kt)
            check('瑞幸出现在**表格行**里（不是正文顺口提一句）',
                  len(krows) >= 2, f'命中 {len(krows)} 行：{krows}')
            check('品牌引力表里瑞幸与 2.2 同档（写清"为什么不给 2.5"）',
                  any('瑞幸' in r and '2.2' in r for r in krows), str(krows[:2]))
            # ⚠️ 这条断言改过两次（v1 → v6 → v7），别照着旧版"修回去"：
            #    v1 时代瑞幸**不在** UPLIFT，钉的是"未标定 / TIER3"；
            #    v6 整表重标定后改为渲染 1.2500（当时 raw 1.2992 被 clamp 截断）；
            #    v7 消双算后 raw 降到 1.1736、收缩 1.1591（**不再撞 clamp**）→ 改为 1.1591；
            #    v8（2026-09-21 切表，只换距离口径）后 raw 1.3660、收缩 **1.3271**、
            #    n 55 → **42**，仍 TIER1 且仍未被截断（尽管已越过 1.25 上界 —— 免 clamp）。
            check('UPLIFT 表里瑞幸如实渲染 v8 标定值 1.3271 / TIER1 / n=42',
                  any('瑞幸' in r and '1.3271' in r for r in krows), str(krows[:2]))
            check('CI 也渲染出来（1.117 ~ 1.250，不是留空）',
                  any('瑞幸' in r and '1.117' in r for r in krows), str(krows[:2]))
            check('静态页写出新口径的名字（"品牌盲"）—— 否则用户不知道 1.3271 从哪来',
                  '品牌盲' in kt)
            # 锚点口径：v8（步行路网）已按引擎口径实测改成"剔除低证据点后 75 家"。
            # ⚠️ 改过两次：v1..v7 是 77 家（直线口径），v8 起 75 家（步行路网口径，
            #    剔 8 家低证据点；标定链纯本地库口径下是 72 家，口径不同不可混用）。
            check('锚点口径已改成实测口径（75 家 / 剔除低证据点）',
                  ('75 家' in kt) and ('低证据' in kt))
            check('已不再声称"全样本中位"（与 calibrate_anchor.py 实际输出不符）',
                  '全样本中位' not in kt)
            # λ 敏感性：v8 按步行路网重算，全区间最低相关 0.937 → 0.921。
            # ⚠️ 断言必须钉**主张**而不是字面：页面里**故意**留着
            #    "（直线口径下为 0.937 / 0.981）"这条口径变更留痕，
            #    所以 `'0.937' not in kt` 会**自己打自己**（同一个坑：
            #    用字面查去验"旧值消失了"，而旧值本来就该作为历史出现一次）。
            check('λ 敏感性渲染 v8 路网口径值（主张是"最低 0.921"，旧值不再作为主张出现）',
                  ('最低 0.921' in kt) and ('最低 0.937' not in kt))
            # 锚点新值必须出现在静态页（v8 重标）
            check('静态页渲染 v8 锚点 4.82 / 0.6024',
                  ('4.82' in kt) and ('0.6024' in kt))
            pg.screenshot(path=str(SHOTS / '11_kb_luckin.png'))

        # 16b 品牌卡 + 三态文案（需要走一趟新流程，故重新载入拿全新会话）
        p('')
        p('--- §16b 奶茶品牌卡：瑞幸可选用 + 表单提示说人话 ---')
        pg.goto(URL, wait_until='load', timeout=60000)
        pg.wait_for_timeout(6000)
        _s2 = _send('我想在杭州滨江开店')
        n2 = 0
        for _ in range(28):
            pg.wait_for_timeout(2000)
            n2 = pg.evaluate("document.querySelectorAll('.cand-card[data-choose]').length")
            if n2:
                break
        info('（第二趟）候选卡片数', str(n2))
        if not n2 or not _s2:
            check('§16b 前置：能再一次走到候选铺源', False,
                  '58 侧失败/超时 —— 本节无法验证（与瑞幸无关，别误读成瑞幸坏了）')
        else:
            pg.query_selector('.cand-card[data-choose]').click()
            ncat2 = 0
            for _ in range(45):
                pg.wait_for_timeout(2000)
                ncat2 = pg.evaluate(
                    "document.querySelectorAll('.cat-card[data-cat]').length")
                if ncat2:
                    break
            info('（第二趟）四品类卡片数', str(ncat2))
            # ⚠️ 检测到 cat-card 后**必须先稳定一下再点**。实机第一版就是在
            #    这里栽的：§12b 点「奶茶」之前天然隔着一堆 §12 的 evaluate 与截图
            #    （好几秒），而 §16b 紧跟着就点 —— 正好撞上工作台重渲，
            #    点击落在已被替换的节点上，**既不报错也没有任何反应**，
            #    表现为"品牌卡 0 张"。所以这里既加等待、也加重试。
            pg.wait_for_timeout(1800)
            nb2 = 0
            for _try in range(3):
                pg.evaluate("(() => { var m=document.querySelector("
                            "'.cat-card[data-cat=\"奶茶\"]'); if (m) m.click(); })()")
                nb2 = 0
                for _ in range(12):
                    pg.wait_for_timeout(1500)
                    nb2 = pg.evaluate(
                        "document.querySelectorAll('.brand-card[data-brand]').length")
                    if nb2:
                        break
                if nb2:
                    break
                info(f'第 {_try + 1} 次点「奶茶」后仍无品牌卡，重试', '')
            bc = pg.evaluate("""(() => Array.prototype.map.call(
                document.querySelectorAll('.brand-card[data-brand]'),
                function (c) { return { b: c.getAttribute('data-brand'),
                    t: (c.innerText||'').replace(/\\s+/g,' ').trim().slice(0, 72) }; }))()""")
            info('品牌卡数', str(nb2))
            # ⚠️ slice 长度要留余量：卡片文案末尾带一个百分比（v6 是 "+25%"、v7 是 "+16%"），
            #    下面的断言要读它 —— 留太短的话，卡片文案再多一个字就会**假红**
            #    （假红和假绿一样坏）。故放宽到 72。
            info('品牌卡列表', json.dumps(bc, ensure_ascii=False)[:420])
            luck = [x for x in (bc or []) if '瑞幸' in (x.get('b') or '')]
            # ⚠️ 2026-09-18 v6/v7：瑞幸进 UPLIFT 后**不再属"无标定组"**，改排"已标定优先"组，
            #    位次由 BRAND_S 决定（实测 v6/v7 下都排到**第 3 张**）。它挤不进去 =
            #    用户根本选不到 = "一等公民"只是代码里的一句空话。
            check('瑞幸出现在奶茶品牌卡里（能选得到，不是只躺在表里）',
                  bool(luck),
                  (f"共 {nb2} 张卡；第 "
                   f"{[i for i, x in enumerate(bc or [], 1) if '瑞幸' in (x.get('b') or '')]} 张 = 瑞幸"
                   if luck else f'共 {nb2} 张卡；**未见瑞幸**（被挤出列表了？）'))
            if luck:
                _t = luck[0].get('t') or ''
                # ⚠️ 行匹配**不要写死数值**：v6 时代这里用 `and '1.25'` 挑 UPLIFT 行 ——
                #    那是靠 CI 上界 1.250 恰好含 "1.25" 的巧合；v7/v8 换成 1.1591/1.3271 后这种匹配
                #    就变成了"依赖巧合"。改用列名 'TIER' 挑行（UPLIFT 表有"等级"列）。
                _up_row = next((r for r in krows if '瑞幸' in r and 'TIER' in r), '')
                _m_up = re.search(r'([01]\.\d{4})', _up_row)
                check('瑞幸卡片标"已标定"（v6 起有真实同商圈标定，不再是 TIER3）',
                      '已标定' in _t, _t)
                # 知识页表值必须 == 引擎值（静态页不许停在旧口径）
                try:
                    from engine.brands import UPLIFT as _UPT
                    _eng = _UPT['瑞幸']
                except Exception as _e:      # 绝不因一个 import 失败就中断整轮探针
                    _eng = None
                    info('引擎 import 失败（该条将判 FAIL）', f'{type(_e).__name__}: {_e}')
                check('知识页渲染的表值 == 引擎 UPLIFT（两个表面不许各说各话）',
                      bool(_m_up) and _eng is not None
                      and abs(float(_m_up.group(1)) - _eng) < 5e-5,
                      f"表值={_m_up.group(1) if _m_up else '?'} 引擎={_eng}")
                # ⚠️ 这条是**跨表面一致性**检查（红线 8），比"出现某字样"强：
                #    卡片上的百分比必须等于**静态知识页 UPLIFT 表里的标定值 − 1**。
                #    v1 时代这段文案写死过"+6%"，改表后卡片会说假话，而所有静态断言照样全绿 ——
                #    所以这里不接受"字面相等"，必须**从另一个表面读出来再对**。
                check('卡片百分比 = (知识页表值 − 1)×100（动态取数，不是写死的文案）',
                      bool(_m_up) and f'+{round((float(_m_up.group(1)) - 1) * 100)}%' in _t,
                      f"表值={_m_up.group(1) if _m_up else '?'} 卡片={_t}")
                pg.evaluate("""(() => { var all=document.querySelectorAll('.brand-card[data-brand]');
                    for (var i=0;i<all.length;i++){
                        if ((all[i].getAttribute('data-brand')||'').indexOf('瑞幸')>=0){
                            all[i].click(); return; } } })()""")
                nf2 = 0
                for _ in range(24):
                    pg.wait_for_timeout(1500)
                    nf2 = pg.evaluate(
                        "document.querySelectorAll('#zl-input-form input[data-key]').length")
                    if nf2:
                        break
                info('（瑞幸）投入表单字段数', str(nf2))
                if not nf2:
                    check('选了瑞幸后出现投入表单', False, '没等到 #zl-input-form')
                else:
                    note2 = pg.evaluate(
                        "(() => { var e=document.querySelector('#zl-input-form .zr-note');"
                        " return e ? e.innerText : ''; })()")
                    fl2 = pg.evaluate(
                        "(() => { var e=document.querySelector('#zl-input-form .zr-floor');"
                        " return e ? {floor:e.getAttribute('data-floor'),"
                        " brand:e.getAttribute('data-brand')} : null; })()")
                    info('瑞幸口径提示行', str(note2)[:220].replace('\n', ' / '))
                    info('瑞幸门限节点', json.dumps(fl2, ensure_ascii=False))
                    # ★★ 本节存在的主要理由：修的就是这句。旧代码只看 fee 真假，
                    #    瑞幸 fee=0 是 falsy → 表单上写「暂无公开加盟费口径」，
                    #    对全市场最出名的"不收加盟费"品牌说了一句假话。
                    check('★★ 瑞幸表单提示说"明确不收加盟费"，且**不出现**"暂无公开口径"',
                          ('明确不收' in (note2 or '')) and ('暂无' not in (note2 or '')),
                          str(note2)[:150])
                    check('同时说清品牌方实际怎么收费（毛利阶梯分成），'
                          '否则用户会以为经营零成本',
                          '毛利' in (note2 or ''))
                    check('瑞幸不设加盟费下限（floor 空/0）——设了会把正常投入误拦',
                          str((fl2 or {}).get('floor')) in ('', '0', 'None', 'null'),
                          json.dumps(fl2, ensure_ascii=False))
                    inp2 = pg.query_selector('#zl-input-form input[data-key="investment"]')
                    if inp2:
                        inp2.fill('1')            # 1 万：低于蜜雪门槛，但对瑞幸不该拦
                        pg.wait_for_timeout(200)
                        pg.click('#zl-input-form button[type="submit"]')
                        pg.wait_for_timeout(1600)
                        w2 = pg.evaluate(
                            "(() => { var e=document.querySelector('#zl-input-form .zr-floor');"
                            " return e ? {cls:e.className, acked:e.getAttribute('data-acked'),"
                            " txt:(e.innerText||'').slice(0,120)} : null; })()")
                        info('瑞幸填 1 万后门限节点', json.dumps(w2, ensure_ascii=False))
                        check('瑞幸填 1 万**不出现**"低于加盟费"标红（三态的正确后果）',
                              not (w2 and 'warn' in (w2.get('cls') or '')
                                   and '加盟费' in (w2.get('txt') or '')),
                              json.dumps(w2, ensure_ascii=False)[:130])
                        pg.screenshot(path=str(SHOTS / '12_luckin_invest_note.png'))

        # ---- §17 专家展示 + 快速演示（2026-09-18 欧文两条诉求）------------------
        # ① 快速演示加**真实反面教材**（低分/一票否决的真实点位）
        # ② 专家卡与快捷条里，「定位」必须压过「拟人名」（改前是反的）
        # ⚠️ 为什么必须走实机：字号是 CSS **层叠算出来**的。
        #    本轮就踩过一次 —— 基础规则已改成 20px/13px，却被后面「字体缩放层」里的
        #    `calc(19.5px * var(--zl-fs))` 静默盖掉；而只看源码的静态断言**照样全绿**。
        p('')
        p('=== §17 专家展示（定位压过拟人名）+ 快速演示反面教材（实机）===')

        pg.evaluate("(() => { var e=document.querySelector('[data-xpage=\"experts\"]');"
                    " if (e) e.click(); })()")
        pg.wait_for_timeout(900)
        ex_cards = pg.evaluate("""(() => {
            var box = document.getElementById('zl-pg-body');
            var out = [];
            if (box) box.querySelectorAll('.zl-ex-card').forEach(function (c) {
                var n = c.querySelector('.zl-ex-name'), t = c.querySelector('.zl-ex-tit');
                if (!n || !t) return;
                var cn = getComputedStyle(n), ct = getComputedStyle(t);
                out.push({whole: (n.innerText || '').replace(/\\s+/g, ' ').trim(),
                          nSize: parseFloat(cn.fontSize), nWeight: parseInt(cn.fontWeight, 10),
                          tSize: parseFloat(ct.fontSize), tWeight: parseInt(ct.fontWeight, 10)});
            });
            return out;
        })()""")
        info('§17a 专家子页卡片（定位/人名 的字号·字重）',
             json.dumps(ex_cards[:3], ensure_ascii=False))
        check('§17a 专家系统子页能打开（前置条件）', bool(ex_cards), f'{len(ex_cards)} 张卡')
        check('§17a 每张卡：定位字号 > 人名、字重 > 人名（定位最显眼）',
              bool(ex_cards) and all(c['nSize'] > c['tSize'] and c['nWeight'] > c['tWeight']
                                     for c in ex_cards))
        pg.screenshot(path=str(SHOTS / '13_experts_role_first.png'))

        # 必须先关掉子页：覆盖层打开时 layoutBar 会主动给专家条加 .hide
        pg.keyboard.press('Escape')
        pg.wait_for_timeout(600)
        info('§17b 专家条状态', str(pg.evaluate(
            "(() => { var b=document.getElementById('zl-xbar');"
            " return b ? {hidden:b.classList.contains('hide')} : null; })()")))
        pg.evaluate("(() => { var t=document.getElementById('xb-toggle'); if (t) t.click(); })()")
        pg.wait_for_timeout(500)
        xrows = pg.evaluate("""(() => {
            var out = [];
            document.querySelectorAll('#zl-xbar .xb-row').forEach(function (b) {
                var k = b.querySelector('.xb-name'), r = b.querySelector('.xb-role'),
                    a = b.querySelector('.xb-alias');
                if (!k || !r || !a) return;
                var cr = getComputedStyle(r), ca = getComputedStyle(a);
                out.push({order: (k.innerText || '').replace(/\\s+/g, ' ').trim(),
                          role: (r.innerText || '').trim(), alias: (a.innerText || '').trim(),
                          rSize: parseFloat(cr.fontSize), rWeight: parseInt(cr.fontWeight, 10),
                          aSize: parseFloat(ca.fontSize), aWeight: parseInt(ca.fontWeight, 10)});
            });
            return out;
        })()""")
        info('§17b 专家条每行（文本顺序 + 字号字重）', json.dumps(xrows[:3], ensure_ascii=False))
        check('§17b 专家条面板 9 行', len(xrows) == 9, f'{len(xrows)} 行')
        check('§17b 每行：定位在**人名之前**，且字号、字重都压过人名',
              bool(xrows) and all(
                  r['order'].find(r['role']) >= 0 and r['order'].find(r['alias']) >= 0
                  and r['order'].find(r['role']) < r['order'].find(r['alias'])
                  and r['rSize'] > r['aSize'] and r['rWeight'] > r['aWeight'] for r in xrows))

        # §17c 快速演示：4 正面 + 2 反面（真反面教材）
        pg.evaluate("(() => { var h=document.querySelector('[data-group=\"demo\"] .zl-group-hd');"
                    " if (h && !h.parentElement.classList.contains('open')) h.click(); })()")
        pg.wait_for_timeout(400)
        demos = pg.evaluate("""(() => {
            var g = document.querySelector('[data-group="demo"]');
            var out = {sub: '', norm: [], bad: []};
            if (!g) return out;
            var s = g.querySelector('.zl-demo-sub');
            if (s) out.sub = (s.innerText || '').trim();
            g.querySelectorAll('.zl-btn').forEach(function (b) {
                var st = getComputedStyle(b);
                var o = {cmd: b.getAttribute('data-cmd'),
                         txt: (b.innerText || '').replace(/\\s+/g, ' ').trim(),
                         bg: st.backgroundColor,
                         hasTitle: !!(b.getAttribute('title') || '')};
                (b.classList.contains('bad') ? out.bad : out.norm).push(o);
            });
            return out;
        })()""")
        info('§17c 快速演示组', json.dumps(demos, ensure_ascii=False))
        check('§17c 演示组有「反面教材」小标题（与正面范例分开）', bool(demos.get('sub')))
        check('§17c 4 个正面范例 + 2 个反面教材',
              len(demos.get('norm') or []) == 4 and len(demos.get('bad') or []) == 2,
              json.dumps(demos.get('bad'), ensure_ascii=False))
        check('§17c 反面按钮配色与正面不同（一眼可分，不会点错）',
              bool(demos.get('bad')) and bool(demos.get('norm'))
              and all(b['bg'] != demos['norm'][0]['bg'] for b in demos['bad']))
        check('§17c 两个反面按钮都带 hover 说明（写清实测低分结论，不是空壳）',
              all(b['hasTitle'] for b in (demos.get('bad') or [])))
        pg.screenshot(path=str(SHOTS / '14_demo_badcases.png'))

        # ---- §18 政策顾问原文链接 + 审计师实时样本量（2026-09-18 新增）--------------
        # 本轮两个"静态断言验不出"的落点：
        #   a) 政策顾问回答后**确定性追加**的「参考链接」块（agent_graph.py 直接拼，
        #      不靠 LLM 复述），要在真实 DOM 里是**可点击的 <a href>**；
        #   b) 模型审计师回答里的锚点样本量要说 **796（扩样可用）**，且**保留 83/77
        #      引擎生效真相**——两者必须同时出现（只有 796 没有真相=混口径，只有
        #      83 没扩样=旧数字没更新）。
        # ⚠️ 断言范围必须收进 .zl-chatcol（对话消息列）：侧栏知识页里本来就有
        #    "83 家"字样（引擎生效口径，正确保留），读 body.innerText 会假绿。
        p('')
        p('=== §18 政策顾问：原文可点链接 / 审计师：实时样本量（796 + 83 并存）===')
        pg.goto(URL, wait_until='load', timeout=60000)
        pg.wait_for_timeout(6000)

        def _chat_col_js(expr):
            # 在**内层真滚动列**（cols 的最后一个，见 sidebar.js 1062-1065 的坑：
            # 两层都带 .zl-chatcol，querySelector 取到的是不滚的外层）里求值
            return pg.evaluate(
                "(() => { var cs = document.querySelectorAll('.zl-chatcol');"
                " var col = cs[cs.length - 1];"
                " if (!col) return null; " + expr + "; })()")

        def _send18(text):
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
                except Exception:
                    continue
            return None

        # ---- §18a 政策顾问：切换 → 问证照/补贴 → 确定性参考链接块
        _send18('/expert startup_policy_advisor')
        _sw1 = False
        for _ in range(30):
            pg.wait_for_timeout(1000)
            if '已切换到' in (_chat_col_js("return col.innerText") or ''):
                _sw1 = True
                break
        check('§18a /expert 切到创业政策顾问', _sw1, '30s 内未见「已切换到」')
        if _sw1:
            _send18('在宁波开奶茶店要办什么证，有没有补贴')
            _links = []
            for _ in range(75):              # LLM 生成 + 确定性追加，最坏 ~150s
                pg.wait_for_timeout(2000)
                _links = _chat_col_js(
                    "return Array.from(col.querySelectorAll('a[href]'))"
                    ".map(function(a){return a.getAttribute('href')||'';})"
                    ".filter(function(h){return h.indexOf('http')===0;})") or []
                if '参考链接' in (_chat_col_js("return col.innerText") or ''):
                    break
            _txt_a = _chat_col_js("return col.innerText") or ''
            info('§18a 参考链接 href', json.dumps(_links[:6], ensure_ascii=False))
            check('§18a 回答后出现「参考链接（原文出处）」块',
                  '参考链接（原文出处）' in _txt_a)
            check('§18a 链接渲染成可点击 <a href>（LLM 不复述也保证出现）',
                  bool(_links))
            check('§18a 链接均为官方域（.gov.cn / 政务服务网）',
                  bool(_links) and all(('.gov.cn' in h or 'zwfw' in h) for h in _links),
                  json.dumps(_links, ensure_ascii=False))
            check('§18a 链接均为 https', all(h.startswith('https://') for h in _links))
            pg.screenshot(path=str(SHOTS / '15_policy_links.png'))

        # ---- §18b 模型审计师：切换 → 问样本量 → 796 主数字 + 83 真相并存
        _send18('/expert model_auditor')
        _sw2 = False
        for _ in range(30):
            pg.wait_for_timeout(1000)
            _t = _chat_col_js("return col.innerText") or ''
            if _t.count('已切换到') >= 2:
                _sw2 = True
                break
        check('§18b /expert 切到模型审计师', _sw2, '30s 内未见第二次「已切换到」')
        if _sw2:
            _send18('你们的流水锚点标定用了多少家门店样本？现在有多少家？')
            _txt_b = ''
            for _ in range(75):              # 审计师 LLM 生成，最坏 ~150s
                pg.wait_for_timeout(2000)
                _txt_b = _chat_col_js("return col.innerText") or ''
                if '796' in _txt_b:
                    break
            info('§18b 审计师回答片段（含样本量的句子）',
                 ' | '.join(l.strip() for l in _txt_b.splitlines()
                            if ('796' in l or '83' in l))[:300])
            check('§18b 审计师回答含扩样可用 796（实时块主数字）', '796' in _txt_b)
            check('§18b 审计师回答保留引擎生效真相 83 家（防混口径）', '83' in _txt_b)
            pg.screenshot(path=str(SHOTS / '16_auditor_796.png'))

        # ---- §19 置顶头透明 + 址南针罗盘 Logo（2026-09-18 策两条：去遮挡方块/换指南针图标）--
        # a) #zl-veya 的实底（--zl-chat 94%~97% 不透明 + blur）就是压住列底罗盘水印的
        #    「更淡色的长方块」——去掉后 computed background 必须完全透明。
        # b) Veyra 弯月 logo → 罗盘 logo：实机只认 computed style 与真实 DOM
        #    （静态断言只能证明"字符串在文件里"）。
        p('')
        p('=== §19 置顶头透明（不遮罗盘）+ 罗盘 Logo（换图标+浮动呼吸）===')
        hd = pg.evaluate("""(() => {
            var h = document.getElementById('zl-veya');
            if (!h) return null;
            var st = getComputedStyle(h);
            var lg = h.querySelector('.zv-logo');
            var ls = lg ? getComputedStyle(lg) : null;
            var html = lg ? lg.innerHTML : '';
            return {
                bg: st.backgroundColor,
                blur: st.backdropFilter || st.webkitBackdropFilter || 'none',
                logoW: ls ? ls.width : '',
                anim: ls ? ls.animationName : '',
                animDur: ls ? ls.animationDuration : '',
                shadow: ls ? ls.filter : '',
                ticks: (html.match(/<line/g) || []).length,
                hasCompassLabel: html.indexOf('址南针罗盘') >= 0,
                hasSouth: html.indexOf('>南</text>') >= 0,
                hasNavy: html.indexOf('#0e353a') >= 0,
                hasGold: html.indexOf('#c9a45c') >= 0,
                hasCream: html.indexOf('#fdfbee') >= 0,
                oldVeyaLeft: html.indexOf('zvP') >= 0 || html.indexOf('>街</text>') >= 0
            };
        })()""")
        info('§19 置顶头/罗盘 Logo', json.dumps(hd, ensure_ascii=False))
        check('§19a 置顶头背景完全透明（罗盘水印从头部区域透出，不再被方块遮挡）',
              bool(hd) and hd.get('bg') in ('rgba(0, 0, 0, 0)', 'transparent'),
              f"bg={hd.get('bg') if hd else 'no-header'}")
        check('§19a 置顶头不再有毛玻璃模糊（blur 会把罗盘线条抹糊）',
              bool(hd) and (hd.get('blur') or 'none') in ('none', ''),
              f"blur={hd.get('blur')}")
        check('§19b logo 槽位 64px 且浮动呼吸动画在跑（zv-bob，策点名保留）',
              bool(hd) and hd.get('logoW') == '64px'
              and hd.get('anim') == 'zv-bob' and hd.get('animDur') == '4s',
              f"w={hd.get('logoW')} anim={hd.get('anim')}/{hd.get('animDur')}")
        check('§19b logo 带光晕 drop-shadow（同原 logo 的 var(--zl-logo-glow)）',
              bool(hd) and 'drop-shadow' in (hd.get('shadow') or ''))
        check('§19c 罗盘刻度环 24 根全部渲染（生成器在真实 DOM 里出了货）',
              bool(hd) and hd.get('ticks') == 24, f"ticks={hd.get('ticks')}")
        check('§19c 罗盘针配色：藏青+金+米白圆底（同原 logo 三色）',
              bool(hd) and hd.get('hasNavy') and hd.get('hasGold') and hd.get('hasCream'))
        check('§19c 「址南针罗盘」标记 + 「南」字小标注都在（针尖指南的语义落位）',
              bool(hd) and hd.get('hasCompassLabel') and hd.get('hasSouth'))
        check('§19c 旧 Veyra 元素零残留（zvP mask / 「街」字）',
              bool(hd) and not hd.get('oldVeyaLeft'))
        pg.screenshot(path=str(SHOTS / '19_header_compass_logo.png'))

        p('')
        p('=' * 66)
        if FAIL:
            p(f'FAILED = {len(FAIL)}：' + ' / '.join(FAIL))
        else:
            p('全部 PASS')
        br.close()


if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    try:
        main()
    except Exception as e:
        import traceback
        p(f'💥 未捕获异常：{type(e).__name__}: {e}')
        p(traceback.format_exc()[:1500])
        FAIL.append('未捕获异常')
    (HERE / '_live_ui_report.txt').write_text('\n'.join(L), encoding='utf-8')
    print(f'\n[写入] {HERE / "_live_ui_report.txt"} / {SHOTS}')
    sys.exit(1 if FAIL else 0)
