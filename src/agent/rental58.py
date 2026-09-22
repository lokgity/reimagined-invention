# -*- coding: utf-8 -*-
"""
rental58.py —— 58同城商铺出租数据抓取（Playwright）
====================================================
从 58 同城商铺出租列表页提取结构化数据: 名称/位置/月租/单价/面积。
数据源: https://{city}.58.com/shangpu/  (如 hz.58.com)

## 2026-09-17 扩量改造（需求：候选店铺太少 + 缺面积/缺租金）

改造前的三个问题，都是**实测**出来的：

1. **只取 10 条、候选满 6 就 break** —— 而列表页一页就有 64~88 条
   （实测：一页真实卡片 165~200 张，页面文本里 `元/月`×72、`万/月`×124、`㎡`×424）。
   → 加 `pages` 参数翻页（实测 `/shangpu/pn2/`、`/pn3/` 均可用），默认 1 页保持旧行为。
2. **卡片筛选条件过严，把"万/月"的铺子整批丢掉** ——
   旧条件是 `'元/月' in t and '㎡' in t`，而 `1.6万/月` 这种写法**不含**"元/月"，
   实测一页里 `万/月` 出现 124 次 > `元/月` 72 次，即被丢掉的可能比留下的还多。
   → 改成 `('元/月' or '万/月')`，面积不再作为**准入**条件（缺面积的照收，后补）。
3. **逐元素 `locator.nth(i).inner_text()` 是 8.4s 的大头** ——
   一页 400 个 li 就是 400 次跨进程调用。
   → 改成一次 `eval_on_selector_all` 批量取文本 + 图片，实测单页由数秒降到 <2s。

另外几处顺带修掉：
- **多页并行**：串行 4 页实测 17.3s（超出"候选检索 ≤12s"的预算），
  改为 4 个独立 context 并发 `goto` + 共享一个 browser → 实测 5s 量级。
- **标题面积补全**：标题常写"店面35平""100㎡"。`_merge_area()` **只补不覆盖**，
  卡片已有面积时优先卡片；标题面积与卡片冲突 >30% 视为不可信不采
  （实测见过卡片结构化字段与标题描述不一致的条目）。
- **详情页补全（`fetch_details`，可选开启）**：列表页给不出面积的、或
  连一个定位线索（路/大厦/loc 第二段）都没有的条目，再开一次详情页取参数区
  （建筑面积 / 月租 / 详细地址）。这是需求④"有些店铺只有区域定位而且没有面积
  和租金，去找更多数据"的直接落地。**只对这两类条目抓**（`_needs_detail`），
  其余不抓 —— 逐条一次导航，全抓会让用户白等十几秒。同样只补不覆盖，
  冲突 >30% 记 `detail_conflict` 不采信（详情页侧栏推荐位实测会串进别的铺子数字）。

`meta` 出参用于区分「取数失败」与「真的没有」——
调用方不许写 `except: return []`。`ok=True` + 空列表 = 真的没有；
`ok=False` = 取数失败（配额/网络/反爬），两者 UI 文案必须不同。

⚠️ 关于"不止 58"（2026-09-17 逐家实测，勿反复重试）：
贝壳/安居客「请输入验证码」、房天下出租频道「未找到相关页面」、
好租验证码、铺专家 403、乐铺/淘铺**域名已不存在**、百姓网 307 跳写字楼、
链家商业只有写字楼且杭州未覆盖；**高德 POI 的 `biz_ext.cost` 是空数组 → 给不了租金**。
结论：除 58 外没有第二个可用的沿街商铺出租源。详见
`docs/品类反推-地点优先与数据补全方案.md`。所以这里的策略是"把 58 榨干"，
而不是假装有多源融合。

- 58 列表页无需登录即可访问(经实测), 用 Playwright 真实浏览器可绕过基础反爬
- 仅供项目演示/研究使用, 遵守 58 同城用户协议, 控制请求频率
"""
import asyncio
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 城市代码映射（58 用拼音短码）
CITY_CODES = {
    '杭州': 'hz', '宁波': 'nb', '温州': 'wz', '嘉兴': 'jx',
    '湖州': 'huz', '绍兴': 'sx', '金华': 'jh', '衢州': 'quzhou',
    '舟山': 'zs', '台州': 'tz', '丽水': 'ls',
}


async def _launch_browser(playwright):
    """Launch the bundled Chromium executable, never the optional headless shell.

    Render builds can install Chromium into the Playwright package itself
    (PLAYWRIGHT_BROWSERS_PATH=0). Passing the path explicitly avoids both
    system Chrome probing and Playwright's default headless-shell resolution.
    """
    executable = playwright.chromium.executable_path
    print(f'[playwright] executable={executable}', flush=True)
    return await playwright.chromium.launch(
        headless=True, executable_path=executable)

# 标题里的面积："35平" / "35 平米" / "100㎡" / "58平方"
# ⚠️ 负向断言 `(?!方)` 防止把"35平方米"里的"35平"重复计数；范围校验另在取值时做
_AREA_IN_TITLE = re.compile(r'(\d{1,4}(?:\.\d)?)\s*(?:平方米|平米|平方|㎡|平(?!方))')

# 单页最多解析多少张卡片（防止把整个 DOM 的 li 都扫一遍）
_MAX_CARDS_PER_PAGE = 400

# 列表项选择器：PC 与移动端结构不同，按"能解析出卡片的数量"择优
_CARD_SELECTORS = ['ul.listUl li', 'ul li', 'li', '[class*=list] li', '.list-item']

# 批量取卡片文本 + 图片的 JS（一次跨进程调用，替代逐元素 inner_text）
# 2026-09-17 扩：顺带取 `href`（详情页链接）—— 列表页常缺面积/只有区域级位置，
# 详情页参数区才有权威的"建筑面积/详细地址"，是候选补全的唯一入口。
_CARDS_JS = """els => els.slice(0, %d).map(e => {
     const img = e.querySelector('img');
     let src = '';
     if (img) {
       src = img.getAttribute('src') || img.getAttribute('data-src') || '';
       if (!src || src.indexOf('lazy_pic') >= 0) {
         const ss = img.getAttribute('srcset') || '';
         const cand = ss.split(',')[0].trim().split(' ')[0];
         if (cand) src = cand;
       }
     }
     const a = e.querySelector('a[href]');
     const href = a ? (a.href || a.getAttribute('href') || '') : '';
     return {t: e.innerText || '', img: src || '', href: href || ''};
   })""" % _MAX_CARDS_PER_PAGE


def _parse_card(text):
    """解析单个卡片的文本, 提取结构化字段。解析不出价格返回 None。"""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    price = price_per = area = None
    title, loc = '', ''
    for l in lines:
        m = re.match(r'([\d.]+)\s*(万|元)/月', l)
        if m and price is None:
            price = float(m.group(1)) * (10000 if m.group(2) == '万' else 1)
            continue
        m2 = re.match(r'([\d.]+)元/㎡/天', l)
        if m2 and price_per is None:
            price_per = float(m2.group(1))
            continue
        m3 = re.match(r'^(\d+)\s*㎡$', l)
        if m3 and area is None:
            a = int(m3.group(1))
            if 5 <= a <= 5000:
                area = a
            continue
    for l in lines:
        if any(k in l for k in ['图', '元/月', '万/月', '元/㎡', '㎡', '建筑面积']):
            continue
        if len(l) > 8:
            title = l
            break
    for l in lines:
        if '-' in l and len(l) < 40 and '地铁' not in l:
            loc = l
            break
    if price is None:
        return None
    return {
        'title': title, 'loc': loc,
        'price': price, 'price_per': price_per, 'area': area,
    }


def _area_from_title(title):
    """从标题补面积（只补不覆盖）。范围 5~5000㎡，超出视为噪声。"""
    if not title:
        return None
    for m in _AREA_IN_TITLE.finditer(title):
        try:
            a = float(m.group(1))
        except Exception:
            continue
        if 5 <= a <= 5000:
            return int(a) if a == int(a) else a
    return None


# ---------------------------------------------------------------
# 房源性质（2026-09-17，用户诉求 3「这些算不算」→ 用户确认：**要算**）
# ---------------------------------------------------------------
# 58 的在租列表里混着两类性质完全不同的条目：
#   · 出租/招租   = 房东/业主招租，谈判对象是房东
#   · 转让/转租   = 别人在转店，谈判对象是现任租户，可能含二手设备/装修、
#                   也可能夹带"承接原租约"的风险
# 用户确认这类**要算进候选**，但必须一眼看出是哪一类 ——
# 否则用户会拿"转让铺"的报价去和"招租铺"比租金，比出来的结论没有意义。
# ⚠️ 判不出就不标（返回 ''），不猜：58 里还有"空铺""新铺"这类中性词。
_DEAL_TRANSFER = ['转让', '转租', '转兑', '出兑', '急转', '接手', '顶手']
_DEAL_RENT = ['出租', '招租', '直租', '业主直租', '房东直租', '免中介']


def _deal_type(text):
    """房源性质：'转让' / '出租' / ''（判不出不标）。"""
    t = text or ''
    # 转让优先：既写"出租"又写"转让"的条目（"转让·可续租"）本质是转让
    if any(k in t for k in _DEAL_TRANSFER):
        return '转让'
    if any(k in t for k in _DEAL_RENT):
        return '出租'
    return ''


def _merge_area(item):
    """面积补全：卡片结构化面积优先；缺则用标题；两者冲突 >30% 判标题不可信。

    ⚠️ 为什么必须做冲突判定：实测见过列表卡片的结构化字段与标题描述不一致
    （多间铺位分开报价），静默采信标题会写出一个错的面积，
    而面积直接决定流水规模 → 结论全偏。
    """
    card_area = item.get('area')
    title_area = _area_from_title(item.get('title') or '')
    if card_area:
        item['area_src'] = 'card'
        if title_area and abs(title_area - card_area) / max(card_area, 1) > 0.30:
            item['area_conflict'] = (card_area, title_area)
        return item
    if title_area:
        item['area'] = title_area
        item['area_src'] = 'title'
    else:
        item['area_src'] = None
    return item


# ---------------------------------------------------------------
# 详情页补全（2026-09-17 新增，需求④"只有区域定位/没有面积租金"）
# ---------------------------------------------------------------
# 详情页文本上限（只取首屏参数区，整页 innerText 含大量推荐位噪声）
_DETAIL_CHARS = 6000

# 参数区：面积 / 月租 / 详细地址。都要求"关键词 + 单位"同时出现，
# 因为详情页侧栏的推荐位里会混进**别的铺子**的数字（实测踩过）。
_DETAIL_AREA = re.compile(
    r'(?:建筑面积|使用面积|套内面积|面积)[：:\s]*([\d.]+)\s*(?:平方米|平米|平方|㎡|平(?!方))')
_DETAIL_RENT_KW = re.compile(
    r'(?:租金|月租|租价|价格)[：:\s]*([\d.]+)\s*(万|元)\s*/?\s*月')
_DETAIL_RENT_ANY = re.compile(r'([\d.]+)\s*(万|元)\s*/\s*月')
_DETAIL_ADDR = re.compile(r'(?:详细地址|商铺地址|地址|位置)[：:\s]*([^\n\r]{4,60})')
# 详情页的"位置"字段常是一整句描述（实测拿到过
# "在东站德胜路绿城春来晓园对面的水墩嘉苑，商铺全部是一楼的有31间…"），
# 直接丢给 geocode 必失败。所以截到第一个标点/空白，去掉"在/位于"等虚词，
# 再限长 —— 这一步是让详情页地址**真的能用于定位**，否则取了也白取。
_ADDR_STOP = re.compile(r'[，,。;；、：:\s]')
_ADDR_LEAD = re.compile(r'^(?:在|位于|地处)+')

# 标题/位置里"能不能定位到具体点"的线索。
# ⚠️ 必须与 agent_graph.search_rental_node 的 geocode 阶梯一致（那里依次试
#   ①路/街/道…+门牌 ②大厦/广场/中心…③loc 的第二段"滨江-四桥南"，全落空才回落区域中心）。
#   但这里问的是**「那条阶梯会不会真的成功」**，所以判据要比阶梯更严：
#   · 路名必须带门牌号 —— 只写"沿街旺铺"时阶梯会拿"杭州沿街"去 geocode，必失败；
#   · 地标必须够"专名"（2 字以上前缀 + 大厦/广场…），光有"城/街"这种常用字不算。
#   这条是自检踩出来的：第一版写成纯字符类，于是"沿街旺铺转让"被当成"能定位"，
#   真正的区域级条目反而不去补详情页了 —— 判宽了等于没判。
_LOCATE_HINT = re.compile(
    r'(?:[\u4e00-\u9fa5]{1,10}(?:路|街|道|巷|弄|大道)[\u4e00-\u9fa5A-Za-z0-9]*\d+\s*号)'
    r'|(?:[\u4e00-\u9fa5A-Za-z0-9]{2,15}(?:大厦|广场|中心|城|里|坊|座|馆|园|苑|庭|府|汇))'
)


def _detail_url_of(href):
    """从卡片里抽详情页链接。抽不到返回 None（该条目就跳过详情补全）。"""
    h = (href or '').strip()
    if not h.startswith('http'):
        return None
    if h.rstrip('/').endswith('/shangpu'):        # 列表页自己，不是详情
        return None
    if re.search(r'/\d{6,}\.shtml', h) or re.search(r'\d{6,}x?\.shtm', h):
        return h
    return None


def _needs_detail(item) -> bool:
    """该条目是否值得多花一次详情页请求。

    ⚠️ 为什么要判而不是"全都抓"：详情页是**逐条一次导航**，12 条并发也要 4~7s，
    而用户就干等在这。只有两类条目真的需要：
      · 缺面积（列表卡片没给，而面积直接决定流水量级）；
      · 连一个定位线索都没有（会回落区域中心 = 用户说的"只有区域定位"）。
    其余条目的详情页信息是冗余的，不看。
    """
    if not item.get('area'):
        return True
    txt = (item.get('title') or '') + (item.get('loc') or '')
    if _LOCATE_HINT.search(txt):
        return False
    return '-' not in (item.get('loc') or '')     # loc 无第二段 -> 定位阶梯只剩回落


def _ok_rent(v):
    return v if 200 <= v <= 2_000_000 else None


def _rent_from_detail(text):
    """详情页取月租。先认"关键词+单位"（可靠），再退回裸 `x元/月`。

    ⚠️ 裸式只取**第一个**匹配：详情页首屏参数区在最上，推荐位在下面，
    所以第一条通常就是本铺挂牌价。取 max 会把"押二付三"的押金当租金。
    也要避开 `2.5元/㎡/天` 这类单价 —— 正则要求 `元` 后紧跟 `/(可选)月`，
    而单价后面是 `/㎡`，天然不匹配。
    """
    m = _DETAIL_RENT_KW.search(text) or _DETAIL_RENT_ANY.search(text)
    if not m:
        return None
    v = float(m.group(1)) * (10000 if m.group(2) == '万' else 1)
    return _ok_rent(v)


def _area_from_detail(text):
    m = _DETAIL_AREA.search(text)
    if not m:
        return None
    try:
        a = float(m.group(1))
    except Exception:
        return None
    if 5 <= a <= 5000:
        return int(a) if a == int(a) else a
    return None


def _addr_from_detail(text):
    """详情页取详细地址；必须含"路/街/号/小区/大厦"等才认，否则是导航文字。"""
    m = _DETAIL_ADDR.search(text)
    if not m:
        return None
    raw = m.group(1).strip()
    if not raw:
        return None
    a = _ADDR_STOP.split(raw)[0]                      # 截到第一个标点/空白
    a = _ADDR_LEAD.sub('', a)[:30].strip()            # 去"在/位于"虚词并限长
    if len(a) < 4 or not re.search(r'(路|街|道|巷|弄|号|小区|大厦|广场|中心)', a):
        return None
    return a


async def _load_detail(browser, url, timeout):
    """并发单元：打开一个详情页，取回 innerText 前 `_DETAIL_CHARS` 字符。"""
    ctx = None
    try:
        ctx = await browser.new_context(viewport={'width': 1400, 'height': 900})
        page = await ctx.new_page()
        await page.goto(url, wait_until='domcontentloaded', timeout=timeout * 1000)
        await page.wait_for_timeout(900)
        txt = await page.evaluate("() => document.body ? document.body.innerText : ''")
        return url, (txt or '')[:_DETAIL_CHARS], None
    except Exception as e:
        return url, '', f'{type(e).__name__}: {str(e)[:60]}'
    finally:
        if ctx is not None:
            try:
                await ctx.close()
            except Exception:
                pass


async def _fetch_details_async(urls, timeout):
    """并发抓详情页。返回 {url: text}；失败的条目**不出现在返回值里**（不写空串占位）。"""
    from playwright.async_api import async_playwright
    out = {}
    async with async_playwright() as p:
        try:
            browser = await _launch_browser(p)
        except Exception as chromium_error:
            raise RuntimeError(
                'Playwright Chromium 不可用；请在部署构建阶段运行 '
                '`PLAYWRIGHT_BROWSERS_PATH=0 playwright install --with-deps chromium`'
            ) from chromium_error
        try:
            results = await asyncio.gather(
                *[_load_detail(browser, u, timeout) for u in urls])
        finally:
            try:
                await browser.close()
            except Exception:
                pass
    for url, txt, err in results:
        if txt and not err:
            out[url] = txt
    return out


def fetch_details(items, timeout=18, max_n=12, budget_s=7.0, meta=None):
    """就地补全条目里缺的 面积/租金/详细地址（详情页参数区）。**只补不覆盖**。

    与 `_merge_area` 同一条纪律：已有值时一概不动；详情页值与已有值冲突 >30%
    只记 `detail_conflict` 不采信（详情页侧栏推荐位实测会串进别的铺子的数字）。
    取不到 / 超时 / 反爬一律**保持原条目不动** —— 绝不用 0 或空值把已有信息冲掉。

    返回补全后的 items（同一个列表对象，就地改）；`meta` 出参报 tried/filled/ok。
    """
    if meta is not None:
        meta.clear()
        meta.update({'ok': False, 'reason': '', 'tried': 0, 'filled': 0,
                     'targets': 0, 'elapsed_s': 0.0, 'source': '58同城·详情页',
                     'fetched_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
    t0 = time.monotonic()
    # 预算 → 并发上限：单页实测 2~3s、4 个 context 并发，所以 budget_s 秒大约
    # 能覆盖 budget_s/2×4 条。按这个经验折算，避免用户为补几个字段等太久。
    max_n = max(1, min(max_n, int(max(1.0, budget_s) / 2 * 4)))
    targets = [it for it in items
               if _detail_url_of(it.get('detail_url')) and _needs_detail(it)]
    targets = targets[:max_n]
    if meta is not None:
        meta['targets'] = len(targets)
    if not targets:
        if meta is not None:
            meta['ok'] = True
            meta['reason'] = '无需补全（面积与定位线索都齐）'
        return items
    try:
        import playwright  # noqa: F401
    except Exception as e:
        if meta is not None:
            meta['reason'] = f'playwright 不可用: {type(e).__name__}'
        return items
    urls = [it['detail_url'] for it in targets]
    try:
        texts = _run_async(_fetch_details_async(urls, timeout))
    except Exception as e:
        if meta is not None:
            meta['reason'] = f'{type(e).__name__}: {e}'
        return items
    filled = 0
    for it in targets:
        txt = texts.get(it.get('detail_url'))
        if not txt:
            continue
        if meta is not None:
            meta['tried'] += 1
        got = 0
        # 面积：只补不覆盖；与标题面积冲突 >30% 不采信（与 _merge_area 同判据）
        if not it.get('area'):
            a = _area_from_detail(txt)
            if a:
                ta = _area_from_title(it.get('title') or '')
                if ta and abs(a - ta) / max(a, 1) > 0.30:
                    it.setdefault('detail_conflict', []).append(('area', a, ta))
                else:
                    it['area'] = a
                    it['area_src'] = 'detail'
                    got += 1
        if not it.get('price'):
            v = _rent_from_detail(txt)
            if v:
                it['price'] = v
                it['price_src'] = 'detail'
                got += 1
        if not it.get('detail_addr'):
            ad = _addr_from_detail(txt)
            if ad:
                it['detail_addr'] = ad
                got += 1
        if got:
            filled += 1
    if meta is not None:
        meta['filled'] = filled
        meta['ok'] = bool(texts)
        meta['elapsed_s'] = round(time.monotonic() - t0, 1)
        if not texts:
            meta['reason'] = '详情页全部未取到（反爬/网络）'
    return items


async def _cards_on_page(page):
    """一次跨进程调用取回本页所有候选卡片的文本与图片。

    返回 [{'t': 文本, 'img': 图url}]，已按"含价格记号"过滤。
    逐个试 `_CARD_SELECTORS` 并取命中最多的一档（PC/移动端结构不同）。
    """
    best = []
    for sel in _CARD_SELECTORS:
        try:
            rows = await page.eval_on_selector_all(sel, _CARDS_JS)
        except Exception:
            continue
        hits = [r for r in rows if r.get('t') and
                ('元/月' in r['t'] or '万/月' in r['t'])]
        if len(hits) > len(best):
            best = hits
        if len(best) >= 20:
            break
    return best


async def _load_one(browser, url, timeout):
    """并发单元：独立 context 打开一个列表页，返回 (url, cards, err)。"""
    ctx = None
    try:
        ctx = await browser.new_context(viewport={'width': 1400, 'height': 900})
        page = await ctx.new_page()
        await page.goto(url, wait_until='domcontentloaded', timeout=timeout * 1000)
        await page.wait_for_timeout(1200)     # 列表懒渲染，等一档即可
        cards = await _cards_on_page(page)
        return url, cards, None
    except Exception as e:
        return url, [], f'{type(e).__name__}: {str(e)[:60]}'
    finally:
        if ctx is not None:
            try:
                await ctx.close()
            except Exception:
                pass


async def _fetch_async(urls, timeout, limit):
    """并发抓取多页。返回 (cards_by_url, page_errors)。"""
    from playwright.async_api import async_playwright
    out, errs = {}, []
    async with async_playwright() as p:
        try:
            browser = await _launch_browser(p)
        except Exception as chromium_error:
            raise RuntimeError(
                'Playwright Chromium 不可用；请在部署构建阶段运行 '
                '`PLAYWRIGHT_BROWSERS_PATH=0 playwright install --with-deps chromium`'
            ) from chromium_error
        try:
            results = await asyncio.gather(
                *[_load_one(browser, u, timeout) for u in urls])
        finally:
            try:
                await browser.close()
            except Exception:
                pass
    for url, cards, err in results:
        out[url] = cards
        if err:
            errs.append(f'{url}: {err}')
    return out, errs


def _run_async(coro):
    """在同步函数里跑协程，且**兼容已在事件循环中的调用方**。

    fetch_shops 的调用点有两条：`asyncio.to_thread(...)`（graph 里）与
    同步调用（negotiation.rent_benchmark）。前者线程内无事件循环，
    后者可能有 —— 直接 `asyncio.run()` 会抛 "cannot be called from a running event loop"，
    所以在有循环时改丢到独立线程执行（与 to_thread 同语义，只是不依赖调用方）。
    """
    try:
        asyncio.get_running_loop()
        loop_running = True
    except RuntimeError:
        loop_running = False
    if not loop_running:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(lambda: asyncio.run(coro)).result()


def fetch_shops(city, limit=60, timeout=25, area_filter=None, pages=1, mobile=False,
                budget_s=12.0, meta=None, detail=False, detail_max=12,
                detail_budget_s=7.0):
    """抓取指定城市的 58 商铺出租列表, 返回结构化条目列表。

    limit      : 条目上限（默认 60）
    pages      : PC 列表页数，1=只抓首页（旧行为）；≥2 时依次抓 /pn2/ /pn3/…
    mobile     : 是否并入移动端 m.58.com 的条目（实测是**另一套条目集合**，可提高覆盖面）
    area_filter: 区域/街道关键词(如"滨江""下沙")，只保留 loc/title 匹配的条目
    budget_s   : 总预算（秒）。超预算就不再发新的页请求 —— 宁可少几页，不让用户干等
    meta       : 可选 dict 出参，写入 ok / reason / pages / raw / deduped / elapsed_s / fetched_at
    detail     : 是否对**缺面积/缺定位线索**的条目再抓一次详情页补全（默认关，
                 因为要多一轮浏览器导航 +4~7s；只有"用户得靠这批候选做决定"时才值得开）
    detail_max / detail_budget_s : 详情页补全的条数上限与时间预算

    取数失败（Playwright 不可用、网络异常）返回空列表且 meta['ok']=False；
    抓到了但没有匹配条目返回空列表且 meta['ok']=True —— 调用方必须区分这两者。
    详情页补全失败**不影响**列表结果（列表值一概保留），只在 meta['detail'] 里记录。
    """
    if meta is not None:
        meta.clear()
        meta.update({'ok': False, 'reason': '', 'pages': [], 'raw': 0, 'deduped': 0,
                     'elapsed_s': 0.0, 'fetched_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                     'source': '58同城'})
    t_start = time.monotonic()
    code = CITY_CODES.get(city, city)
    urls = []
    if pages and pages >= 1:
        urls.append(f'https://{code}.58.com/shangpu/')
        for n in range(2, pages + 1):
            urls.append(f'https://{code}.58.com/shangpu/pn{n}/')
    if mobile:
        urls.append(f'https://m.58.com/{code}/shangpu/')
    try:
        import playwright  # noqa: F401
    except Exception as e:
        if meta is not None:
            meta['reason'] = f'playwright 不可用: {type(e).__name__}'
        return []

    # 并发抓：页面之间互不依赖，一次性全发（预算只用来"少发几页"，不发第二轮）
    if budget_s and pages + (1 if mobile else 0) > 1:
        # 预算是"总时长上限"的软约束：并发下页数不影响首字节时间，
        # 所以这里只在**页数特别多**时截断，避免一次开十几个 Chrome context。
        max_parallel = 4
        if len(urls) > max_parallel:
            urls = urls[:max_parallel]
            if meta is not None:
                meta['stopped_by'] = f'并发上限 {max_parallel} 页'
    cards_by_url, page_errors = {}, []
    try:
        cards_by_url, page_errors = _run_async(_fetch_async(urls, timeout, limit))
    except Exception as e:
        if meta is not None:
            meta['reason'] = f'{type(e).__name__}: {e}'
        return []
    if meta is not None and page_errors:
        meta['page_errors'] = page_errors

    items, seen = [], set()
    for url in urls:
        cards = cards_by_url.get(url) or []
        if meta is not None:
            meta['raw'] += len(cards)
        added = 0
        for row in cards:
            if len(items) >= limit:
                break
            item = _parse_card(row.get('t') or '')
            if not item:
                continue
            item = _merge_area(item)
            full = (item['loc'] or '') + (item['title'] or '')
            # 房源性质（出租/转让）—— 不过滤，只标注；用户明确要算转让铺
            item['deal'] = _deal_type(full)
            # 区域过滤: loc(如"滨江-四桥南") 或 title 需包含区域词
            if area_filter and area_filter not in full:
                continue
            if not item.get('title'):
                continue
            key = (item['title'].strip(), (item['loc'] or '').strip())
            if key in seen:
                continue
            seen.add(key)
            src = row.get('img') or ''
            item['img'] = src if src.startswith('http') else None
            item['from'] = url
            item['detail_url'] = _detail_url_of(row.get('href'))
            items.append(item)
            added += 1
        if meta is not None:
            meta['pages'].append({'url': url, 'added': added})

    # ---- 详情页补全（可选；服务需求④"只有区域定位/没有面积租金"）----
    if detail and items:
        dmeta = {}
        try:
            fetch_details(items, max_n=detail_max, budget_s=detail_budget_s, meta=dmeta)
        except Exception as e:      # 补全失败绝不能把已抓到的列表一起丢掉
            dmeta = {'ok': False, 'reason': f'{type(e).__name__}: {e}'}
        if meta is not None:
            meta['detail'] = dmeta

    if meta is not None:
        # 只要**有一页成功返回**就算取数成功；全页失败才算失败
        got_any = any(cards_by_url.get(u) for u in urls)
        meta['ok'] = bool(got_any)
        meta['deduped'] = len(items)
        meta['elapsed_s'] = round(time.monotonic() - t_start, 1)
        if not items and got_any:
            meta['reason'] = '抓取成功但无匹配条目（区域关键词可能过窄）'
        elif not got_any:
            meta['reason'] = '全部页面未取到卡片（反爬/网络）'
    return items


if __name__ == '__main__':
    m = {}
    shops = fetch_shops('杭州', limit=60, pages=3, mobile=True, meta=m, detail=True)
    print(f'抓到 {len(shops)} 条 | meta={m}')
    miss_area = sum(1 for s in shops if not s.get('area'))
    print(f'缺面积 {miss_area} / {len(shops)}'
          f' | 详情页补全 {m.get("detail", {}).get("filled", 0)}'
          f'/{m.get("detail", {}).get("targets", 0)} 条')
    for s in shops[:15]:
        print(f"  [{s.get('loc')}] {(s.get('title') or '')[:26]} | {s.get('price'):.0f}元/月"
              f" | {s.get('area')}㎡({s.get('area_src')}) | img={'Y' if s.get('img') else 'N'}"
              f" | detail={'Y' if s.get('detail_url') else 'N'}")
