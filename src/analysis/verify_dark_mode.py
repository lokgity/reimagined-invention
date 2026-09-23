# -*- coding: utf-8 -*-
"""
verify_dark_mode.py —— 双主题（亮/暗）对比度门禁
=================================================
背景（2026-09-23 策实机反馈）：
    agent 默认开在暗色模式，但**两套皮各判各的主题**：
      · `public/sidebar.js`（自绘面板：左操作栏/右数据栏/仿真大屏）
            = 「暗为默认（:root）+ html:not(.dark) 覆盖亮色」——完整
      · `public/app.css`（Chainlit 消息区 markdown：标题/表格/引用/加粗）
            = **纯亮色写死，全文件 0 处 prefers-color-scheme** —— 残缺
    后果（策截图所见）：
      ① 分析栏标题/加粗用 #1e293b / #0f172a，深字贴深底 → 看不见；
      ② 右侧数据栏斑马纹 #f8fafc 白底，配 sidebar.js 的
         --zl-card-val:#f2efe0 米色数字 → 白底米字看不见；
      ③ h3 左边框 #b8860b 暗金、blockquote 底色 #e6f2f1 浅青 → 暗色下很脏。

本套件钉住四件事（都是"改了会静默坏、且本地看不出来"的那类）：
    §1  app.css 必须存在 prefes-color-scheme 判据（不允许再回到"只写亮色"）
    §2  两套皮必须**用同一个开关**（html.dark / html:not(.dark)），
        不许 app.css 用 @media 而 sidebar.js 用 class —— 否则同页两种主题并存
    §3  暗色分支里不许再出现那批已知不可读的硬编码值
    §4  sidebar.js 必须监听系统主题变化（原实现只在启动读一次 matchMedia，
        设置页那句"跟随系统会随操作系统自动切换"是空头承诺）

⚠️ 纪律（本项目第一高发错 —— 同一件事的多个"表面"）：
    改主题涉及**三处表面**：app.css / sidebar.js / .chainlit/config.toml(?v= 版本号)。
    版本号不 bump，浏览器吃缓存，用户刷新也看不到改动 → 必须一起钉。
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CSS = ROOT / 'public' / 'app.css'
JS = ROOT / 'public' / 'sidebar.js'
CFG = ROOT / '.chainlit' / 'config.toml'

fails = 0
n = 0


def ck(cond, label):
    global fails, n
    n += 1
    if cond:
        print('  OK   ' + label)
    else:
        fails += 1
        print('  FAIL ' + label)


def read(p):
    return p.read_text(encoding='utf-8')


print('=' * 62)
print('§1 app.css 必须带双主题判据')
print('=' * 62)

css = read(CSS)

# 注释里的说明文字会提到 prefers-color-scheme，先剥掉注释再判，否则自指误伤
css_nc = re.sub(r'/\*.*?\*/', '', css, flags=re.S)

ck('html:not(.dark)' in css_nc,
   'app.css 用 html:not(.dark) 给亮色值（与 sidebar.js 同一判据）')
ck(':root' in css_nc,
   'app.css 有 :root 定义（暗为默认）')

# 关键变量必须同时出现在两个块里 —— 只定义一处 = 另一主题下取值落空
var_names = [
    '--zl-ink',          # 标题字色（本次事故主角）
    '--zl-zebra',        # 斑马纹底（本次事故主角）
    '--zl-strong',       # 加粗字色（本次事故主角）
    '--zl-line-strong',  # h3 左边框
    '--zl-brand',        # 表头底 / 引用左边框
    '--zl-brand-soft',   # 引用底色
    '--zl-line',         # 表格分割线
]
for v in var_names:
    # 数「定义处」次数：:root 一次 + html:not(.dark) 一次 = 2
    cnt = len(re.findall(re.escape(v) + r'\s*:', css_nc))
    ck(cnt >= 2, f'{v} 在暗/亮两块里都有定义（实测 {cnt} 处，要求 ≥2）')

print()
print('=' * 62)
print('§2 两套皮必须同一个开关（禁止一边 @media 一边 class）')
print('=' * 62)

js = read(JS)
js_nc = re.sub(r'/\*.*?\*/', '', js, flags=re.S)

ck('html:not(.dark)' in js_nc,
   'sidebar.js 用 html:not(.dark) 定义亮色')
ck("classList.add('dark')" in js_nc and "classList.remove('dark')" in js_nc,
   'sidebar.js 的 applyTheme 真正把 .dark 挂/摘到 <html>')

# app.css 不许用 @media (prefers-color-scheme) 另起一套 —— 那会和 html.dark 打架
css_media_dark = re.search(
    r'@media\s*\(\s*prefers-color-scheme\s*:\s*dark\s*\)', css_nc)
ck(css_media_dark is None,
   'app.css 没有另起 @media(prefers-color-scheme:dark)'
   '（否则与 sidebar.js 的 html.dark 判据冲突，同页两主题）')

print()
print('=' * 62)
print('§3 暗色分支不许再有已知不可读的硬编码值')
print('=' * 62)

# 拆出两个块：:root{...} 与 html:not(.dark){...}
def block_of(text, selector):
    m = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', text)
    return m.group(1) if m else ''


dark_block = block_of(css_nc, ':root')
light_block = block_of(css_nc, 'html:not(.dark)')

ck(bool(dark_block), '成功切出 :root 暗色块')
ck(bool(light_block), '成功切出 html:not(.dark) 亮色块')

# 这三个值出现在暗色块里 = 事故复发
BAD_IN_DARK = {
    '#1e293b': '深墨字（暗底上读不清）',
    '#0f172a': '近黑字（暗底上读不清）',
    '#f8fafc': '近白底（暗色下突兀，且与米色数字撞）',
    '#e6f2f1': '浅青底（暗色下过亮）',
    '#b8860b': '暗金（暗底上读不清）',
}
for bad, why in BAD_IN_DARK.items():
    ck(bad not in dark_block.lower(),
       f'暗色块里没有 {bad}（{why}）')

# 反向断言：亮色块里必须**原样保留**这些值 —— 改造前那套不能被动过
for keep in ['#1d6f78', '#1e293b', '#e2e8f0', '#f8fafc', '#0f172a']:
    ck(keep in light_block.lower(),
       f'亮色块原样保留 {keep}（亮色皮不许被改动）')

# body/html 上的字色不能是纯黑或纯白之外的低对比组合
ck('--zl-ink' in dark_block,
   '--zl-ink 在暗色块里有显式值（不允许靠继承）')

# 暗色下 --zl-ink 必须是亮色（#RRGGBB 的亮度够高）
m = re.search(r'--zl-ink\s*:\s*(#[0-9a-fA-F]{6})', dark_block)
if m:
    hexv = m.group(1).lstrip('#')
    r_, g_, b_ = (int(hexv[i:i + 2], 16) for i in (0, 2, 4))
    # 相对亮度（sRGB 简化式）：> 0.5 才算亮字
    lum = (0.2126 * r_ + 0.7152 * g_ + 0.0722 * b_) / 255.0
    ck(lum > 0.5,
       f'暗色 --zl-ink={m.group(1)} 是亮字（相对亮度 {lum:.3f} > 0.5）')
else:
    ck(False, '暗色 --zl-ink 可解析出 #RRGGBB')

print()
print('=' * 62)
print('§4 sidebar.js 必须监听系统主题变化')
print('=' * 62)

ck('matchMedia' in js_nc, 'sidebar.js 用了 matchMedia')
ck(re.search(r"addEventListener\(\s*'change'", js_nc) is not None
   or "addListener" in js_nc,
   "sidebar.js 给 matchMedia 挂了 change 监听（跟随系统能实时切，不必刷新）")
# 监听回调里必须判 currentThemeMode()==='system'，否则手动选了浅色会被系统抢走
ck('currentThemeMode' in js_nc,
   '变更回调里用 currentThemeMode() 判模式（手动浅/深色不被系统覆盖）')

print()
print('=' * 62)
print('§5 三处表面必须同步：样式改了，?v= 版本号要 bump')
print('=' * 62)

cfg = read(CFG)
m_css = re.search(r'custom_css\s*=\s*"([^"]+)"', cfg)
m_js = re.search(r'custom_js\s*=\s*"([^"]+)"', cfg)
ck(m_css is not None, 'config.toml 有 custom_css')
ck(m_js is not None, 'config.toml 有 custom_js')


def ver_of(url):
    mm = re.search(r'\?v=(\d+)', url or '')
    return int(mm.group(1)) if mm else None


v_css, v_js = ver_of(m_css.group(1) if m_css else ''), ver_of(m_js.group(1) if m_js else '')
# 版本号必须存在（无版本号 = 浏览器强缓存，改了看不到）
ck(v_css is not None, f'custom_css 带版本号（实测 v={v_css}）')
ck(v_js is not None, f'custom_js 带版本号（实测 v={v_js}）')
# 本次改造把两者各推了一版
ck(v_css is not None and v_css >= 19,
   f'app.css 版本号 ≥19（本次暗色改造，实测 {v_css}）')
ck(v_js is not None and v_js >= 31,
   f'sidebar.js 版本号 ≥31（本次加主题监听，实测 {v_js}）')

print()
print('=' * 62)
print(f'FAILED = {fails}  /  共 {n} 项')
# ⚠️ 结尾行必须是 `FAILED = N`：run_regression.py 的失败计数正则里
#    `共\s*(\d+)\s*项\s*FAIL` 会把**总项数**当失败数（本套件有「共 N 项 FAIL M」
#    两段数字，该正则捕获的是 N）。统一成 FAILED = N 才无歧义。
print('=' * 62)

sys.exit(1 if fails else 0)
