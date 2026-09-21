# -*- coding: utf-8 -*-
"""light_theme_probe.py —— 浅色主题定向探针（`live_ui_probe.py` 的补充面）

为什么需要它：项目铁律「改子页面样式必须**两主题都验**」（踩过硬编码亮色在浅底
看不清的坑：`--zl-warn-tx` 那次）。而 `live_ui_probe.py` 固定跑应用默认的**深色**主题，
浅色那一面没人盯 —— 本脚本专门补这一面；当前覆盖欢迎语标题（渐变可读性 + 花纹），
将来给别的子页面加浅色验收，往这里加即可。

⚠️ 与 `live_ui_probe.py` 同属**实机**层，**不进**离线门禁（要起真服务，天然 flaky），
   只作信息性验证。**改样式的收尾动作 = 两个探针都跑一遍。**

渐变是 4 个**写死的 hex**，深浅各一套 —— 换个主题到底还看不看得清，只能实机看。

用法（需先起 Chainlit）：
  C:\\Python312\\python.exe src/analysis/light_theme_probe.py
输出：同目录 _light_theme_report.txt + 项目根 _ui_shots/11_welcome_motif_light.png
"""
import io
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SHOTS = ROOT / '_ui_shots'
SHOTS.mkdir(exist_ok=True)
L, FAIL = [], []

H1_SEL = ('[class*="message-content"] h1,[class*="Markdown"] h1,'
          '[class*="markdown"] h1')


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


def main():
    from playwright.sync_api import sync_playwright

    URL = 'http://127.0.0.1:8502'
    p('浅色主题定向验证：欢迎语标题渐变 + 花纹')
    with sync_playwright() as pw:
        br = None
        # 与 live_ui_probe 一致：必须优先 channel='chrome'
        for kw in ({'headless': True, 'channel': 'chrome'}, {'headless': True}):
            try:
                br = pw.chromium.launch(**kw)
                info('浏览器启动方式', str(kw))
                break
            except Exception as e:
                info('启动失败，换下一种', str(e)[:70])
        if br is None:
            check('Playwright 浏览器可启动（前置条件）', False)
            return

        pg = br.new_page(viewport={'width': 1600, 'height': 950})
        pg.goto(URL, wait_until='domcontentloaded')
        for _ in range(30):
            if pg.query_selector(H1_SEL):
                break
            pg.wait_for_timeout(1000)
        check('欢迎语 h1 在实机里出现', bool(pg.query_selector(H1_SEL)))

        # Chainlit 用 html.dark 表示深色主题 → 去掉即切浅色
        pg.evaluate("document.documentElement.classList.remove('dark')")
        pg.wait_for_timeout(1200)

        hl = pg.evaluate("""(() => {
          const h = document.querySelector(
            '[class*="message-content"] h1,[class*="Markdown"] h1,[class*="markdown"] h1');
          if (!h) return {found: false};
          const cs = getComputedStyle(h), r = h.getBoundingClientRect();
          let pin = '';
          try { pin = decodeURIComponent(cs.getPropertyValue('--zl-pin') || ''); } catch (e) {}
          return {found: true,
                  dark: document.documentElement.classList.contains('dark'),
                  bgImg: cs.backgroundImage.slice(0, 120),
                  bgSize: cs.backgroundSize,
                  pin: pin.slice(0, 400),
                  left: Math.round(r.left), top: Math.round(r.top),
                  w: Math.round(r.width), h: Math.round(r.height)};
        })()""")
        check('主题已切到浅色（html 不再带 .dark）', hl.get('dark') is False)
        if not hl.get('found'):
            check('h1 可读', False)
        else:
            info('h1 盒子（left/top/宽/高）',
                 f"{hl.get('left')}/{hl.get('top')}/{hl.get('w')}x{hl.get('h')}")
            info('background-size / position',
                 f"{hl.get('bgSize')} / 见 CSS")
            info('computed background-image', str(hl.get('bgImg'))[:110])
            check('浅色下渐变仍是 4 色标 linear-gradient',
                  'linear-gradient' in (hl.get('bgImg') or '')
                  and (hl.get('bgImg') or '').count('rgb') >= 4,
                  str(hl.get('bgImg'))[:100])
            check('浅色花纹用的是深金那一份（--zl-pin 含 a8843c）',
                  'a8843c' in (hl.get('pin') or ''), str(hl.get('pin'))[:90])
            check('浅色下 h1 同样收缩到内容宽（fit-content 生效）',
                  (hl.get('w') or 9999) <= 460, f"w={hl.get('w')}")

            # 像素采样：浅色下**文字比背景暗**，所以每列取最暗像素（深色那份是取最亮）
            try:
                from PIL import Image
                box = {'x': hl['left'] + 48, 'y': hl['top'],
                       'width': max(1, hl['w'] - 96), 'height': hl['h']}
                im = Image.open(io.BytesIO(pg.screenshot(clip=box))).convert('RGB')

                def _lu(_px):
                    return (_px[0] * .299 + _px[1] * .587 + _px[2] * .114) / 255 * 100

                cols = []
                for cx in range(im.width):
                    mn = 999.0
                    for cy in range(im.height):
                        v = _lu(im.getpixel((cx, cy)))
                        if v < mn:
                            mn = v
                    cols.append(mn)
                # ⚠️ 必须剔除"没有笔画的列"：那种列的最暗像素就是**背景**本身
                #    （米黄 ~95），混进来会把极差虚抬成"背景 vs 文字"的对比度
                #    （第一版就这么报出 78.1，走势里那格 95 就是漏网的背景列）。
                #    判据：高百分位 ≈ 背景列，暗于它 20 以上的才算真有字。
                _bgv = sorted(cols)[int(len(cols) * 0.85)] if cols else 0.0
                txt = [v for v in cols if v < _bgv - 20]
                info('背景基线 / 文字列数', f'{_bgv:.1f} / {len(txt)}（共 {len(cols)} 列）')
                span = (max(txt) - min(txt)) if txt else 0.0
                seg = max(1, len(txt) // 10) if txt else 1
                trend = [sum(txt[i:i + seg]) / len(txt[i:i + seg])
                         for i in range(0, len(txt), seg)]
                info('浅色下文字明度沿 x 走势（每列最暗像素，0=黑 100=白）',
                     ' '.join(f'{v:.0f}' for v in trend))
                check('浅色主题也能看出渐变：明度极差 ≥ 28（与深色同一门槛）',
                      span >= 28,
                      f'极差 {span:.1f}（最暗 {min(txt) if txt else 0:.1f} / '
                      f'最亮 {max(txt) if txt else 0:.1f}）')
            except Exception as e:
                check('浅色像素采样可执行（依赖 PIL）', False, f'{type(e).__name__}: {e}')

        pg.screenshot(path=str(SHOTS / '11_welcome_motif_light.png'))
        br.close()

    p('')
    p('=' * 66)
    p('FAILED = %d' % len(FAIL))
    for f in FAIL:
        p('  - ' + f)
    with io.open(HERE / '_light_theme_report.txt', 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(L) + '\n')
    return 1 if FAIL else 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
