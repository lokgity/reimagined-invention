# -*- coding: utf-8 -*-
"""check_deploy_env.py —— 部署环境自检（公网服务器 / 本机通用，只读不改数据）
================================================================================
为什么需要这个脚本
------------------
2026-09-23 排查「公网部署后嘉兴海宁取数失败」时踩到的坑：
**同一个 `ok=False` 背后至少有两种完全不同的原因，处理方式也完全不同** ——
  · Chromium 不存在（部署镜像没装浏览器）→ 装浏览器，5 分钟解决；
  · 页面返回验证码（站点反爬）→ 装浏览器没用，得换抓取入口。
而 UI 上都显示成"58 取数失败（反爬/网络）"，用户会去"稍后再试/换个区域"，
**白折腾**。所以这个脚本把两层分开测，直接给出该修哪一层。

三组实测（每组都打印"判据"，不打印"感觉"）
------------------------------------------
 ① 浏览器层：playwright 包在不在、chromium 可执行文件在不在、能不能真的启动；
 ② PC 站  ：`https://{code}.58.com/shangpu/`
 ③ 移动端 ：`https://m.58.com/{code}/shangpu/` 与 `/pn2/`（翻页是否有效）

判据：页面文本里出现 `验证码/访问频繁/安全验证/captcha` 即判"反爬"；
      否则用"含 `元/月`或`万/月` 的文本块数"当可解析条目数的近似。

用法
----
    python src/analysis/check_deploy_env.py            # 默认 嘉兴 / 海宁
    python src/analysis/check_deploy_env.py 杭州 滨江

⚠️ 本脚本**不进离线门禁**（要联网，属于 flaky 组）。
"""
import asyncio
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / 'src'))

CITY = sys.argv[1] if len(sys.argv) > 1 else '嘉兴'
AREA = sys.argv[2] if len(sys.argv) > 2 else '海宁'

MARKERS = ('验证码', '访问频繁', '安全验证', 'captcha', 'robot')
UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')

L = []


def p(*a):
    s = ' '.join(str(x) for x in a)
    print(s)
    L.append(s)


def report_verdict():
    """汇总结论。"""
    p('')
    p('=' * 72)
    p('结论与修复指引')
    p('=' * 72)


def main():
    p('=' * 72)
    p('部署环境自检')
    p('=' * 72)
    p(f'python   = {sys.version.split()[0]}  ({sys.executable})')
    p(f'platform = {sys.platform}')
    p(f'目标     = {CITY} / {AREA}')

    # ---- ① 浏览器层 ----------------------------------------------------
    p('')
    p('-' * 72)
    p('① 浏览器层')
    p('-' * 72)
    try:
        import playwright  # noqa: F401
        p('playwright 包: 已安装')
        pw_ok = True
    except Exception as e:
        p(f'playwright 包: **未安装** ({type(e).__name__})')
        pw_ok = False

    exe = None
    if pw_ok:
        async def probe_exe():
            from playwright.async_api import async_playwright
            async with async_playwright() as pw:
                return pw.chromium.executable_path
        try:
            exe = asyncio.run(probe_exe())
        except Exception as e:
            p(f'取 executable_path 失败: {type(e).__name__}: {e}')
        if exe:
            exists = os.path.exists(exe)
            p(f'chromium 路径: {exe}')
            p(f'chromium 存在: {exists}  ← 不存在 = 部署镜像漏装浏览器')

    if exe and not os.path.exists(exe):
        p('')
        p('  ❌ 这就是「取数失败」的第一种原因（与反爬无关）。修复：')
        p('     构建阶段执行（把这行写进 Dockerfile / 部署脚本）：')
        p('       PLAYWRIGHT_BROWSERS_PATH=0 playwright install --with-deps chromium')
        p('     ⚠️ 装进**包目录**（PATH=0）才不会因运行用户不同而找不到；')
        p('        --with-deps 需要 root，所以必须放在构建阶段，不能运行时补救。')
        report_verdict()
        return

    if exe:
        async def try_launch():
            from playwright.async_api import async_playwright
            async with async_playwright() as pw:
                b = await pw.chromium.launch(
                    headless=True, executable_path=pw.chromium.executable_path)
                v = b.version
                await b.close()
                return v
        try:
            v = asyncio.run(try_launch())
            p(f'chromium 启动: **OK**（version={v}）')
        except Exception as e:
            p(f'chromium 启动: **失败** {type(e).__name__}: {str(e)[:150]}')
            p('  → 缺系统依赖（Linux 上常见）。补: playwright install-deps chromium')

    # ---- ② / ③ 抓取入口实测 ---------------------------------------------
    from agent.rental58 import CITY_CODES
    code = CITY_CODES.get(CITY, CITY)
    p('')
    p(f'城市代码: {CITY} → {code}')

    urls = [
        ('PC 站      ', f'https://{code}.58.com/shangpu/'),
        ('移动端 1 页', f'https://m.58.com/{code}/shangpu/'),
        ('移动端 2 页', f'https://m.58.com/{code}/shangpu/pn2/'),
    ]

    async def probe_pages():
        from playwright.async_api import async_playwright
        out = []
        async with async_playwright() as pw:
            b = await pw.chromium.launch(
                headless=True, executable_path=pw.chromium.executable_path)
            for tag, url in urls:
                ctx = await b.new_context(
                    viewport={'width': 1400, 'height': 900}, user_agent=UA)
                pg = await ctx.new_page()
                try:
                    await pg.goto(url, wait_until='domcontentloaded',
                                  timeout=25000)
                    await pg.wait_for_timeout(1500)
                    txt = await pg.evaluate(
                        "() => document.body ? document.body.innerText : ''")
                    out.append((tag, url, txt or '', None))
                except Exception as e:
                    out.append((tag, url, '', f'{type(e).__name__}: {str(e)[:90]}'))
                await ctx.close()
            await b.close()
        return out

    if exe:
        p('')
        p('-' * 72)
        p('② / ③ 抓取入口实测')
        p('-' * 72)
        try:
            rows = asyncio.run(probe_pages())
        except Exception as e:
            p(f'实测失败: {type(e).__name__}: {e}')
            rows = []
        pc_blocked = mobile_ok = None
        for tag, url, txt, err in rows:
            if err:
                p(f'{tag} {url}\n         ERR {err}')
                continue
            hit = [m for m in MARKERS if m in txt]
            n_month = len(re.findall(r'(?:万|元)/月', txt))
            p(f'{tag} {url}')
            p(f'         长度={len(txt)}  "X/月"={n_month}  含"{AREA}"={txt.count(AREA)}'
              f'  反爬={hit or "无"}')
            if 'PC 站' in tag:
                pc_blocked = bool(hit)
            else:
                mobile_ok = (not hit) and n_month > 0

        report_verdict()
        if pc_blocked and mobile_ok:
            p('  ✅ 移动端可用、PC 站被反爬 —— 这是 2026-09 起的新常态。')
            p('     修复：把抓取重心挪到 m.58.com（PC 站降级为"可选试一次"）。')
            p('     代码位置：src/agent/agent_graph.py 的 RENTAL58_PAGES / '
              'RENTAL58_MOBILE；')
            p('     以及 src/agent/rental58.py 的 urls 拼装处。')
        elif not mobile_ok:
            p('  ⚠️ 移动端也没拿到内容 —— 这台机器的出口 IP 可能被 58 限流。')
            p('     先确认不是 Chromium 问题；若是 IP 问题，只能降频/换出口，')
            p('     或在服务里如实降级（不要假装"没有铺子"）。')
        else:
            p('  PC 站可用（与 2026-09 的观测不同，可能站点策略有回摆）。')
    else:
        report_verdict()
        p('  浏览器层不可用 → 先修 ①，否则 ②③ 无从测起。')


if __name__ == '__main__':
    main()
    (HERE / '_check_deploy_env.txt').write_text('\n'.join(L), encoding='utf-8')
