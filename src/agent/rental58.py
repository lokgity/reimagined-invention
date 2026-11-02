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
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 区县身份：归一化与"是不是区县词"的判据都取自 `zj_districts`（唯一事实源，不另造表）
from agent.zj_districts import DISTRICT_KEYS, district_key, district_full  # noqa: E402

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


# 58 卡片里**平台自己标的业态/铺型**。实测原样（2026-09-26 从抓下来的卡片里翻出来）：
#   `安选 临街门面 临街 可餐饮 可明火` / `写字楼配套` /
#   `安选 免租1个月 社区底商 临街 可明火` / `安选 档口摊位 临街 可餐饮 可明火`
#
# ⚠️ 三件事必须说清，别误用：
#   ① 这是 **58 的标注**（中介自己填的），**不是真值** —— 只能当"对照"，
#      不能当 ground truth；算出来的是**一致率**，不是"准确率"。
#   ② 咱原来的 `_parse_card` **只取 价格/面积/标题/位置**，这一段**一直被丢掉**
#      （它不含 `元/月`、也没有 `-`，所以既进不了 title 也进不了 loc）——
#      等于白抓了一批带标签的数据。现在补上。
#   ③ 用途只有一个：**评估 #11 业态判定的对照样本**（算一致率 + 混淆矩阵）。
#      它**不参与任何测算**，也不进候选卡片。
#
# 按长度降序 —— 先认 `社区底商` 再认 `底商`，否则短词会先把长词吃掉。
_PLATFORM_BIZ_KW = sorted((
    '临街门面', '商业街店铺', '社区底商', '住宅底商', '写字楼配套', '档口摊位',
    '沿街商铺', '购物中心', '商业综合体', '美食城档口', '超市外租区',
    '商业街', '底商',
), key=len, reverse=True)


def _platform_biz_of(lines):
    """从卡片行里挑出**平台标的业态**；找不到返回 ''（不猜）。"""
    for l in lines:
        if len(l) > 40 or any(k in l for k in ['元/月', '万/月', '元/㎡', '㎡', '建筑面积']):
            continue
        for kw in _PLATFORM_BIZ_KW:
            if kw in l:
                return kw
    return ''


def _parse_card(text):
    """解析单个卡片的文本, 提取结构化字段。解析不出价格返回 None。"""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    price = price_per = area = None
    title, loc = '', ''
    for l in lines:
        m = re.match(r'([\d.]+)\s*(万|元)/月', l)
        if m and price is None:
            price = float(m.group(1)) * (10000 if m.group(2) == '万' else 1)
            # ⚠️ 2026-09-23：**移动端把「价格 + 面积」写在同一行**。
            # 实测 m.58.com 卡片 innerText 的最后一行是 `'7350元/月 245㎡'`，
            # 而下面那条面积规则是 `^(\d+)\s*㎡$`（要求**整行只有面积** —— 那是 PC 站
            # 「价格一行、面积一行」的格式）。原来的 `continue` 让这一行被价格用掉就跳过，
            # 面积永远轮不到 ⇒ **租金有、面积全 None**（PC 站被验证码拦后 100% 复现）。
            # 这里先在本行内找一次面积，PC 那条规则保持不动（两种格式都兼容）。
            if area is None:
                m_inline = re.search(r'(\d{1,4})\s*㎡', l)
                if m_inline:
                    a_inline = int(m_inline.group(1))
                    if 5 <= a_inline <= 5000:
                        area = a_inline
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
        # 平台自己标的业态（见 `_PLATFORM_BIZ_KW` 的注释：**只用于评估对照**，不进测算）
        '平台业态': _platform_biz_of(lines),
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
# 区县归属判定（2026-09-25 新增，#8 地点解析）
# ---------------------------------------------------------------
# 58 的 loc 实测有两种形态（宁波·全市首页 148 张卡片）：
#   ① 结构化：`庄市·萌恒大厦-宁波市-镇海区-同心路888号…`
#              `西门·恒茂商业广场-宁波市-海曙区-广安路224号029幢`          —— 16/148
#   ② 简写：  `首南·天健巷127号` / `集士港·布政西路225号` / `长丰·宁南北路363号`
#              首段是**商圈/街道名**（首南→鄞州区、集士港→海曙区、长丰→鄞州区）
#   ③ 一个区县名都没有（loc 与 title 都干净）                              —— 91/148
#
# 改造前是 `if area_filter and area_filter not in full`（纯字符串包含），两个方向都错：
#   **误杀**：`loc='轻纺城·塘西中路'` 真在海曙，只因没写"海曙"就被丢；
#   **误收**：全市页里 9 条江北 + 8 条鄞州 + 3 条镇海 + 3 条北仑 + 2 条奉化，
#            标题里恰好写着"海曙"就会被当海曙留下。
_LOC_DISTRICT_PAT = re.compile(
    r'-[\u4e00-\u9fa5]{2,4}市-([\u4e00-\u9fa5]{2,8}?(?:区|县|市))-')

_BIZ_DISTRICT_CACHE = {}      # (商圈, 城市) -> 区县；进程内缓存，查本地 SQLite 不打外网
_EXTRACT_DISTRICT = None

# 商圈 -> 区县 的最小样本门槛。
# ⚠️ 为什么要门槛（2026-09-25 实测）：本地 POI 库是 4.4 万条的**抽样**，
#    不是全量 —— 样本过薄时会给出**假阳性**：
#      `'中河'`（宁波中河街道，实际在鄞州区）在库里只有 **2 条**，全是北仑区的
#      "中河路(地铁站)" ⇒ 判成北仑区（错）；
#    而判对的那些样本都厚：首南 7 / 集士港 7 / 长丰 7 / 庄市 8 / 孔浦 / 东部新城。
#    按"宁少不掺沙"，这里**宁可判不出**（返回 None，该条落进"无法判定"象限被丢），
#    也不给一个错的区县。代价：极少数真·小众商圈会判不出（如轻纺城只有 1 条）。
_BIZ_MIN_N = 3


def _extract_district(text):
    """延迟取 `agent_graph.extract_district`（区县名的**唯一识别入口**，不另写一套）。

    ⚠️ 必须延迟导入：`agent_graph` **顶层**就 `from agent.rental58 import fetch_shops`，
       这里若顶层反向 import 会成环。取到一次即缓存。
    """
    global _EXTRACT_DISTRICT
    if _EXTRACT_DISTRICT is None:
        from agent.agent_graph import extract_district
        _EXTRACT_DISTRICT = extract_district
    return _EXTRACT_DISTRICT(text)


def _biz_district(biz, city_cn):
    """商圈/街道名 -> 区县（查本地 POI 库，**按城市限定**）。

    ⚠️ 必须限定城市：实测不限定会**跨市串味** ——
       '中河' 串到衢州柯城区（宁波中河街道 vs 衢州"中河沿"）、
       '轻纺城' 串到湖州长兴县 / 绍兴越城区（宁波轻纺城在**海曙区石碶**）。
       限定 `city='宁波市'` 后：首南→鄞州区、集士港→海曙区、庄市→镇海区、孔浦→江北区 ✓
    ⚠️ 还要过 `_BIZ_MIN_N` 样本门槛（见该常量注释）：样本太薄宁可判不出，不给假阳性。
    """
    if not biz or len(biz) < 2:
        return None
    key = (biz, city_cn)
    if key in _BIZ_DISTRICT_CACHE:
        return _BIZ_DISTRICT_CACHE[key]
    out = None
    try:
        from data.query import get_conn
        conn = get_conn()
        rows = conn.execute(
            'SELECT adname, COUNT(*) c FROM poi WHERE city = ? AND name LIKE ? '
            'GROUP BY adname HAVING c >= ? ORDER BY c DESC LIMIT 1',
            (city_cn, f'%{biz}%', _BIZ_MIN_N)).fetchall()
        # 不再 close()：连接由 data.query.get_conn() 按线程缓存复用（2026-09-27 P0-3）
        if rows and rows[0][0]:
            out = rows[0][0]
    except Exception:
        out = None
    _BIZ_DISTRICT_CACHE[key] = out
    return out


def _item_district(item, city_cn):
    """58 条目的区县归属 —— 三级判定，判不出返回 `''`（**不猜**）。

    ① `loc` 的结构化 `-{市}-{区}-` 段 —— 平台自己给的，最权威
    ② `loc` 首段的商圈/街道名 → 查本地 POI（限该城市）
    ③ `loc` / `title` 里出现的区县名
    三样都落空 ⇒ `''`：调用方必须按"判不出"处理，**不许**当成都算或都算对。

    返回值**统一成规范全称**（'海曙' → '海曙区'）：`extract_district` 对短名入参
    返回短名，不归一化就会出现"同一个区两种写法"（见 `zj_districts.district_full`）。
    """
    loc = item.get('loc') or ''
    m = _LOC_DISTRICT_PAT.search(loc)
    if m:
        return district_full(m.group(1))
    if loc:
        biz = re.split(r'[·\-—]', loc)[0].strip()
        d = _biz_district(biz, city_cn)
        if d:
            return district_full(d)
    return district_full(_extract_district(loc)
                         or _extract_district(item.get('title') or '') or '')


def _area_filter_ok(item, area_filter):
    """区域过滤判定（替换原来的纯字符串包含）。`item['district']` 需先由 `_item_district` 填好。

    - `area_filter` 本身是**区县词**（'海曙'/'海曙区'/'义乌'）⇒ 按**区县身份**比对；
      判不出区县的条目**一律不要** —— 宁少不掺沙，不拿"可能在"充数。
    - 不是区县词（'下沙'/'文三路' 这类商圈/路名）⇒ **退回原包含匹配**，
      不为这些词引入新语义，既有行为逐字不变。
    """
    want = area_filter or ''
    if not want:
        return True
    if district_key(want) in DISTRICT_KEYS:
        got = item.get('district') or ''
        return bool(got) and district_key(got) == district_key(want)
    full = (item.get('loc') or '') + (item.get('title') or '')
    return want in full


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


async def _fetch_details_async(urls, timeout, total_timeout=7.0):
    """并发抓详情页。返回 {url: text}；失败的条目**不出现在返回值里**（不写空串占位）。"""
    from playwright.async_api import async_playwright
    out = {}
    async with async_playwright() as p:
        try:
            browser = await asyncio.wait_for(
                _launch_browser(p), timeout=max(3.0, min(15.0, total_timeout)))
        except Exception as chromium_error:
            raise RuntimeError(
                'Playwright Chromium 不可用；请在部署构建阶段运行 '
                '`PLAYWRIGHT_BROWSERS_PATH=0 playwright install --with-deps chromium`'
            ) from chromium_error
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*[_load_detail(browser, u, timeout) for u in urls]),
                timeout=max(3.0, float(total_timeout)))
        except asyncio.TimeoutError:
            results = [(u, '', '详情抓取总时限已到') for u in urls]
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
        texts = _run_async(
            _fetch_details_async(urls, timeout, total_timeout=budget_s))
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
    last_error = None
    for attempt in range(2):
        ctx = None
        try:
            ctx = await browser.new_context(
                viewport={'width': 1400, 'height': 900},
                user_agent=(
                    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'))
            page = await ctx.new_page()
            response = await page.goto(
                url, wait_until='domcontentloaded', timeout=timeout * 1000)
            status = response.status if response is not None else None
            if status in (403, 429):
                return url, [], f'HTTP {status}（站点拒绝或限流）'
            await page.wait_for_timeout(1200)     # 列表懒渲染，等一档即可
            cards = await _cards_on_page(page)
            if cards:
                return url, cards, None
            body = (await page.locator('body').inner_text())[:1200].lower()
            markers = ('验证码', '访问频繁', '安全验证', 'robot', 'captcha')
            if any(marker.lower() in body for marker in markers):
                return url, [], '页面返回验证/反爬提示'
            return url, [], f'HTTP {status or "未知"}（页面无可解析卡片）'
        except Exception as e:
            last_error = f'{type(e).__name__}: {str(e)[:100]}'
            if attempt == 0:
                await asyncio.sleep(1.5)
        finally:
            if ctx is not None:
                try:
                    await ctx.close()
                except Exception:
                    pass
    return url, [], f'重试 1 次后仍失败：{last_error}'


async def _fetch_async(urls, timeout, limit, total_timeout=12.0):
    """并发抓取多页，且有硬性总时限。返回 (cards_by_url, page_errors)。"""
    from playwright.async_api import async_playwright
    out, errs = {}, []
    async with async_playwright() as p:
        try:
            browser = await asyncio.wait_for(
                _launch_browser(p), timeout=max(3.0, min(15.0, total_timeout)))
        except Exception as chromium_error:
            raise RuntimeError(
                'Playwright Chromium 不可用；请在部署构建阶段运行 '
                '`PLAYWRIGHT_BROWSERS_PATH=0 playwright install --with-deps chromium`'
            ) from chromium_error
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*[_load_one(browser, u, timeout) for u in urls]),
                timeout=max(3.0, float(total_timeout)))
        except asyncio.TimeoutError:
            results = [(u, [], '抓取总时限已到（页面可能响应慢或被限流）')
                       for u in urls]
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
    # ⚠️ 2026-09-23（问题①）：`CITY_CODES.get(city, city)` 的默认值是**危险**的 ——
    #    查不到就把 city 原样当域名，拼出 `https://海宁.58.com/shangpu/` 这种
    #    无效地址（真机实测：4 路全部 0 条、耗时 21.4s 才失败，用户白等）。
    #    这里补一层**区县反推**：'海宁' → '嘉兴'、'嘉兴海宁' → '嘉兴'。
    #    放在 fetch_shops 内部而不是只改调用方，是因为本项目**第一高发错**
    #    就是"同一件事有几处表面"——调用方会新增，防御要长在最内层。
    code = CITY_CODES.get(city)
    if code is None:
        try:
            from agent.zj_districts import DISTRICT_TO_CITY, DISTRICT_TO_CITY_SHORT
            c2 = city or ''
            for c in ('杭州', '宁波', '温州', '嘉兴', '湖州', '绍兴',
                      '金华', '衢州', '舟山', '台州', '丽水'):
                if c in c2:
                    c2 = c
                    break
            else:
                for dist in sorted(DISTRICT_TO_CITY, key=len, reverse=True):
                    if dist in (city or ''):
                        c2 = DISTRICT_TO_CITY[dist]
                        break
                else:
                    for short in sorted(DISTRICT_TO_CITY_SHORT, key=len, reverse=True):
                        if short in (city or ''):
                            c2 = DISTRICT_TO_CITY_SHORT[short]
                            break
            code = CITY_CODES.get(c2)
            if meta is not None:
                meta['city_resolved'] = f'{city} → {c2}' if code else ''
            city = c2 if code else city
        except Exception:
            pass
    # 反推也失败 → 不要拿中文当域名发请求（那只会白等 20 秒）
    if not code:
        if meta is not None:
            meta['reason'] = (f'城市「{city}」不在浙江 11 个地级市内，'
                              '也没有对应的 58 分站；请给出地级市或浙江区县名。')
            meta['ok'] = False
            meta['elapsed_s'] = 0.0
        return []
    urls = []
    # ⚠️ 2026-09-23：抓取重心从 PC 站挪到**移动端**。
    # PC 站（*.58.com）已被验证码全面接管（实测 jx/jiaxing/haining/hz 四个域名返回**同一个**
    # 验证码页），**翻多少页都是同一个验证码页** —— 白等，还白占并发额度（总并发上限 4 路）。
    # 而移动端 `m.58.com/{code}/shangpu/pn2/`、`pn3/` 实测有效（内容与首页不同）。
    # 所以 `pages` 现在的语义是「**移动端**翻到第几页」，PC 只留首页做"站点策略回摆"的探测。
    # ⚠️ 顺序即优先级：条目按 URL 顺序累积、攒够 limit 就停
    #    （`if len(items) >= limit: break`）。所以**关键词页必须排在最前**。
    #    2026-09-26 实测踩到：PC 首页原本在第 1 位，某轮站点突然放行、它一次吃掉
    #    40 个名额，而 PC 条目的 loc 大多**不带区名**（判不出归属 ⇒ 全被丢弃），
    #    关键词页只剩 20 个名额 —— 极端情况下 PC 独占名额，候选直接归零。
    #    PC 首页本来只是"站点策略回摆的探测"，产出为 0 是常态、产出非 0 反而污染候选池。
    area_kw = str(area_filter or '').strip()
    # ⚠️ 这个条件**故意不写成** `if area_filter:` —— 下面 fetch 循环里的区域过滤也写作
    #    `if area_filter`，而门禁 verify_place_first §13 是按**字面顺序**校验
    #    「deal 标记必须早于区域过滤」的（`rb.find(...) < rb.find('if area_filter')`）。
    #    这里多一个同名条件会让那把尺子量到错的位置（2026-09-25 踩到：误报 FAIL）。
    if area_kw:
        # ⚠️ 2026-09-25（#8）：**在源头按区县/商圈检索**，而不是抓完一大把再筛。
        #    实测（宁波·海曙）：
        #      全市首页 148 张 → 只能判定 15 条属于海曙；
        #      `m.58.com/nb/shangpu/?key=海曙` 89 张 → 能判定 58 条 —— **召回 3.9 倍**，
        #      且 89 张里只有 1 张落在别的城市（西湖区），**没有跨区误收**；
        #      对照全市页混进 9 江北 + 8 鄞州 + 3 镇海 + 3 北仑 + 2 奉化。
        urls.append(f'https://m.58.com/{code}/shangpu/?key={quote(area_kw)}')
    if pages and pages >= 1:
        urls.append(f'https://{code}.58.com/shangpu/')
    if mobile:
        urls.append(f'https://m.58.com/{code}/shangpu/')
        for n in range(2, pages + 1):
            urls.append(f'https://m.58.com/{code}/shangpu/pn{n}/')
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
        cards_by_url, page_errors = _run_async(
            _fetch_async(urls, timeout, limit, total_timeout=budget_s))
    except Exception as e:
        if meta is not None:
            meta['reason'] = f'{type(e).__name__}: {e}'
        return []
    if meta is not None and page_errors:
        meta['page_errors'] = page_errors

    items, seen = [], set()
    n_dropped = 0          # 被区域过滤丢掉的条数
    n_dropped_nodist = 0   # 其中因为"标题/位置都没写区县、判不出归属"而丢的
    city_cn = f'{city}市'
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
            # 区县归属（三级判定，判不出为 ''）——**只在真要做区域过滤时算**：
            # 全城查询没有消费方，算了等于往记录里塞一个未经验证的区县（违反"不猜"），
            # 还要为每个商圈多查一次本地库。
            item['district'] = _item_district(item, city_cn) if area_filter else ''
            # 区域过滤: 区县词按**区县身份**比对（不再靠字符串包含，详见 _area_filter_ok）
            if area_filter and not _area_filter_ok(item, area_filter):
                n_dropped += 1
                if not item['district']:
                    n_dropped_nodist += 1
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
        # 区域过滤的账本（**不静默**）：丢了多少、其中多少是"判不出区县"丢的
        meta['district_scope'] = area_filter or ''
        meta['district_dropped'] = n_dropped
        meta['district_unknown'] = n_dropped_nodist
        if not items and got_any:
            meta['reason'] = ('抓取成功但无匹配条目（区域关键词可能过窄，'
                              '或该区县的挂牌都只在标题写了商圈、判不出归属）')
        elif not got_any:
            errors = meta.get('page_errors') or []
            if any('HTTP 403' in e or 'HTTP 429' in e or '验证/反爬' in e
                   for e in errors):
                meta['reason'] = '页面返回反爬/限流或验证提示'
            # ⚠️ `'总时限'` 这一项是 2026-09-23 补的，不是可有可无：
            # `_fetch_async` 超时时写的是「抓取总时限已到（页面可能响应慢或被限流）」——
            # **既不含 "Timeout" 也不含 "超时"**（用的是"总时限"），于是超时被这条判据漏掉，
            # 落到最后的 else 显示成"页面未取到卡片（网络或页面结构变化）"，
            # **把"超时"误报成"页面结构变了"**，排查时被带偏（线上那次就吃了这个亏）。
            elif any('Timeout' in e or '超时' in e or '总时限' in e
                     for e in errors):
                meta['reason'] = '页面请求超时（网络或站点响应慢）'
            else:
                meta['reason'] = '页面未取到卡片（网络或页面结构变化）'
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
