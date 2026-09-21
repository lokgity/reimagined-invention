# -*- coding: utf-8 -*-
"""verify_place_first.py —— 入口 B「地点优先」+ 候选扩量 + 租金/面积三态回归（**离线门禁组成员**）
================================================================================
覆盖用户四条诉求对应的实现（2026-09-17）：

| 诉求 | 落点 | 本文件的断言 |
|---|---|---|
| ① 说"想在哪儿开店"要进**推荐店铺**环节，再反推开什么店 | `place_first` 新 phase + `collect_place_node` | §1 意图真值表 · §2 谓词 · §3 节点行为 |
| ② 推荐出租店铺时**增加店铺数量** | `search_rental_node` 共用常量 | §4 常量/排序/截断 |
| ③ 一开始**确定品类**时也增加可选店铺数量 | 同上（同一个节点，一处改动两边生效） | §4 断言两条路共用常量 |
| ④ 有些店铺**只有区域定位、无面积无租金**，要去找更多数据 | 58 多页+移动端 · 标题解析面积 · 详情页补全 · 同区参考带推算 · 品类标准面积兜底 · 三态标注 | §5 三态 · §6 参考带 · §7 详情页解析 |

**为什么"缺租金一律不出经营评分"要单独设断言**：用户确认的决策点是
「目标抓60展示15 一律不出 能进但是显著标注 不做」——改造前系统会静默按
¥8000 测算，最后给出一个看起来很确定的**假结论**。这条纪律一旦被改回去，
不会有任何报错，只会有一批错得很自信的结论。所以必须钉住。

运行：C:\\Python314\\python.exe src/analysis/verify_place_first.py
输出：同目录 _place_first_report.txt
"""
import asyncio
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / '.pylibs'))
# 离线门禁必须真的离线（run_regression.py 也会置，独立跑时靠这一行）
os.environ.setdefault('ZL_EXPERT_LLM_DISABLE', '1')

OUT = HERE = Path(__file__).resolve().parent
L, FAILS = [], []


def p(*a):
    s = ' '.join(str(x) for x in a)
    print(s)
    L.append(s)


def check(cond, label, detail=''):
    p(f'  {"PASS" if cond else "FAIL"}  {label}' + (f'  |  {detail}' if detail else ''))
    if not cond:
        FAILS.append(label)


def sect(t):
    p('')
    p('=' * 74)
    p(t)
    p('=' * 74)


def _read(rel):
    f = ROOT / rel
    return f.read_text(encoding='utf-8') if f.exists() else ''


def strip_comments(src, kind):
    """断言跑在**去注释**文本上：本项目的注释会把"被否定的旧写法"一起写进去
    （例如 `rent = state.get('rent') or 8000` 就写在 docstring 里解释为什么删），
    拿带注释的原文去断言"该写法已不存在"，注释会自己打倒自己。"""
    if kind == 'js':
        src = re.sub(r'/\*.*?\*/', '', src, flags=re.S)
        return re.sub(r'(?m)^[ \t]*//.*$', '', src)
    src = re.sub(r'(?s)""".*?"""', '', src)
    return re.sub(r'(?m)^[ \t]*#.*$', '', src)


def _fn_body(src, header, maxlen=8000):
    i = src.find(header)
    if i < 0:
        return ''
    seg = src[i:i + maxlen]
    for marker in ('\n  function ', '\n  var ', '\n  /* ----',
                   '\n# ---', '\nasync def ', '\ndef ', '\nclass ', '\n# ='):
        j = seg.find(marker, len(header) + 1)
        if j > 0:
            seg = seg[:j]
    return seg


GRAPH = strip_comments(_read('src/agent/agent_graph.py'), 'py')
R58_RAW = _read('src/agent/rental58.py')
R58 = strip_comments(R58_RAW, 'py')
JS = strip_comments(_read('public/sidebar.js'), 'js')
APP = strip_comments(_read('src/ui/app_chainlit.py'), 'py')

from agent.agent_graph import (  # noqa: E402
    classify_node, collect_place_node, select_shop_node, analyze_node,
    _wants_place_first, _has_place_hint, _mentions_existing_shop,
    _fill_field_states, _rank_candidates, cand_state_brief, area_filter_of,
    CAND_TOTAL, CAND_POOL,
    RENTAL58_LIMIT, RENTAL58_PAGES, RENTAL58_MOBILE, RENTAL58_DETAIL,
)


def mk(msg, **over):
    st = {
        'messages': [{'role': 'user', 'content': msg}],
        'phase': 'intro', 'missing_info': [], 'candidates': [], 'list_shown': False,
        'hooks': {'steps': []},
    }
    st.update(over)
    return st


async def phase_of(msg, **over):
    return (await classify_node(mk(msg, **over))).get('phase')


# =============================================================== §1 意图真值表
async def s1():
    sect('§1 意图真值表：说"想在某个地方开店"必须进 place_first（改造前三个入口全断）')
    p('  改造前的实测：')
    p('    「我想在杭州滨江开店」      -> no_shop   被反问"想开什么品类"（他没想好）')
    p('    「滨江这边怎么样，适合开店吗」-> chat     被"吗"字判成闲聊（真 bug）')
    p('    「杭州下沙适合开什么店」    -> shop_first 追问月租（他没铺子，答不出->死胡同）')
    p('')
    must_place = [
        '我想在杭州滨江开店',
        '想在杭州下沙开店',
        '杭州下沙适合开什么店',
        '滨江这边怎么样，适合开店吗',
        '在滨江开个店',
        '我想在宁波鄞州开个店，开什么好',
        '滨江这边适合做什么生意',
    ]
    for t in must_place:
        ph = await phase_of(t)
        check(ph == 'place_first', f'应判 place_first 却得到 {ph}：{t}')
        p(f"    [{'OK ' if ph == 'place_first' else 'FAIL'}] {t:<28} -> {ph}")

    p('')
    p('  对照：**不能**被新入口抢走（这是最容易改坏的一处 —— 优先级只加不减）')
    must_not = [
        ('我有个铺子但不知道开什么', ('shop_first',),
         '有铺子 -> shop_first（分界线：手里到底有没有这个铺子）'),
        ('店铺已经租下来了，滨江这边做什么好', ('shop_first',),
         '已租下 -> 仍是 shop_first，即使句中有"滨江这边"'),
        ('我想开奶茶店', ('no_shop',),
         '有品类 -> A 流程，不该进反推'),
        ('帮我找杭州滨江的铺子', ('place_first',),
         '2026-09-17 诉求①：没品类 -> 一律先进 place_first 推铺源（改造前是 no_shop 反问品类）'),
        ('杭州滨江春晓路 60 号，月租 8000，40 平，想开便利店', ('have_shop',),
         '具体铺位+品类 -> 选址评估'),
        ('奶茶店毛利率一般多少？', ('chat',),
         '纯提问 -> 咨询闸门'),
        ('我店已经开了，月流水8万', ('diagnose',),
         '已开店+报流水 -> 经营诊断（优先级在 _wants_shop_first 之前）'),
        # ⚠️ 这两条是**真回退**（2026-09-17 被 verify_flow_v2 抓到）：
        #    新入口最初没加咨询闸门，于是"杭州开店租金什么水平？"这种纯问行情的话
        #    被判成"想开店" → 用户会被塞一张候选铺源列表，而他问的只是行情。
        #    分界线是 `_wants_start_flow` 里的意向词（适合开店/能开店/开什么店…）：
        #    "滨江这边怎么样，适合开店吗" 命中 -> 穿透闸门；"租金什么水平" 不命中 -> 被拦。
        ('杭州开店租金什么水平？', ('chat',),
         '纯问行情 -> chat（**不许**被 place_first 抢走）'),
        ('在滨江开店需要投入多少钱？', ('chat',),
         '纯问投入 -> chat（同上）'),
    ]
    for t, expect, why in must_not:
        ph = await phase_of(t)
        check(ph in expect, f'应判 {expect} 却得到 {ph}：{t}', why)
        p(f"    [{'OK ' if ph in expect else 'FAIL'}] {t:<28} -> {ph}   ({why})")

    p('')
    p('  已在 place_first 阶段：说品类 -> 仍在 place_first 交给节点转 A 流程；提问 -> chat')
    ph = await phase_of('就开奶茶吧', phase='place_first')
    check(ph == 'place_first', f'place_first 阶段说品类不该掉出去，得到 {ph}')
    p(f"    [{'OK ' if ph == 'place_first' else 'FAIL'}] 就开奶茶吧（prev=place_first） -> {ph}")
    ph = await phase_of('奶茶店毛利一般多少？', phase='place_first')
    check(ph == 'chat', f'place_first 阶段提问应转 chat，得到 {ph}')
    p(f"    [{'OK ' if ph == 'chat' else 'FAIL'}] 奶茶店毛利一般多少（prev=place_first） -> {ph}")


# =============================================================== §2 谓词
def s2():
    sect('§2 谓词单测：_wants_place_first / _has_place_hint / _mentions_existing_shop')
    for t, exp in [('我想在杭州滨江开店', True), ('杭州下沙适合开什么店', True),
                   ('滨江这边适合开店吗', True), ('我想开个店', True),
                   ('我有个铺子但不知道开什么', False), ('我想开奶茶店', False),
                   ('帮我找杭州滨江的铺子', True), ('', False)]:
        got = _wants_place_first(t)
        check(got is exp, f'_wants_place_first({t!r}) == {exp}', f'实际 {got}')
    for t, exp in [('杭州滨江', True), ('滨江这边', True), ('西湖区文三路', True),
                   ('开什么好', False)]:
        got = _has_place_hint(t)
        check(got is exp, f'_has_place_hint({t!r}) == {exp}', f'实际 {got}')
    check(_mentions_existing_shop('铺子已经租下来了') is True, '已有铺子词命中')
    check(_mentions_existing_shop('我想在滨江开店') is False, '"想在滨江开店"不是已有铺子')
    check(area_filter_of('杭州滨江') == '滨江',
          'area_filter_of 去掉城市前缀', area_filter_of('杭州滨江'))
    check(area_filter_of('滨江') == '滨江', '无前缀时原样返回')


# =============================================================== §3 节点行为
async def s3():
    sect('§3 collect_place_node：只收地点，**不问租金面积**（改造前的死胡同就在这）')
    r = await collect_place_node(mk('我想开店'))
    check(r.get('phase') == 'place_first', '没给地点 -> 留在 place_first 追问')
    check(set(r.get('missing_info') or []) == {'地点'},
          f'只缺"地点"（不得追问月租/面积），得到 {r.get("missing_info")}')
    msg = (r['messages'] or [])[-1]['content']
    # 注意：文案里**允许**出现"带租金和面积"（那是在说候选列表自带这两个字段），
    # 不许出现的是**向用户索要**这两个数。所以断言的是"没有索要句式"。
    check('想开在哪个地方' in msg and all(
        k not in msg for k in ('多少平', '月租多少', '多少租金', '租金多少')),
        '追问文案只问地点、不得向用户索要月租/面积', msg.replace('\n', ' ')[:90])
    check(r.get('place_first_mode') is True, '置位 place_first_mode')

    r = await collect_place_node(mk('我想在杭州滨江开店', address='杭州滨江'))
    check(r.get('phase') == 'search_rental', f'给了地点 -> 直接去搜铺源，得到 {r.get("phase")}')
    check(r.get('place_first_mode') is True, '搜铺源时仍标记 place_first_mode')

    r = await collect_place_node(
        mk('我想在杭州滨江开店', address='杭州滨江', category='奶茶'))
    check(r.get('phase') == 'search_rental' and r.get('place_first_mode') is False,
          '顺口说了品类 -> 收回 place_first_mode（交回 A 流程，不再反推）', str(r.get('phase')))


# =============================================================== §4 候选扩量
def s4():
    sect('§4 候选扩量：抓 60 / 展示 15（用户确认），且**两条路共用同一套常量**')
    check(CAND_TOTAL == 15, f'展示上限 CAND_TOTAL == 15（实际 {CAND_TOTAL}）')
    check(RENTAL58_LIMIT == 60, f'抓取上限 RENTAL58_LIMIT == 60（实际 {RENTAL58_LIMIT}）')
    # 2026-09-17（诉求②）：两级兜底删除后，候选池必须自己开够 ——
    # 池 < 展示上限时，"排序"就退化成"按抓取顺序取前 N 个"，用户可能点的前几家全是缺字段的。
    check(CAND_POOL >= CAND_TOTAL,
          f'候选池 CAND_POOL({CAND_POOL}) 必须 >= 展示上限({CAND_TOTAL})，'
          f'否则排序失效（旧值 12 是靠兜底补齐的，兜底已删）')
    check(RENTAL58_PAGES >= 2 and RENTAL58_MOBILE is True,
          f'多页({RENTAL58_PAGES}) + 移动端({RENTAL58_MOBILE}) 均已启用')
    # 诉求③：一开始确定品类那条路也走 search_rental_node，所以必须确认是**同一个节点**
    # maxlen=20000 与 §12/§13 一致：该函数体很长（含定位阶梯 + 三态 + 区域转让风险），
    # 默认 8000 会截断到 CAND_TOTAL 之前，让"用常量"的断言误报。
    body = _fn_body(GRAPH, 'async def search_rental_node(', maxlen=20000)
    check('CAND_POOL' in body and 'CAND_TOTAL' in body,
          'search_rental_node 用的是常量（收池 CAND_POOL / 展示 CAND_TOTAL），不是写死的数字')
    check('place_mode' in body,
          'play_first 与 A 流程共用该节点（place_mode 只影响文案，不影响条数）')
    check(GRAPH.count("add_node('search_rental'") == 1,
          'search_rental 只注册一次 —— 两处候选入口共用同一个节点'
          f'（实际注册 {GRAPH.count("add_node('search_rental'")} 次）')

    p('')
    p('  排序：字段完整度优先 -> 距离近的优先；**缺字段的不丢弃只排后面**')
    cands = [
        {'name': '缺面积缺租金', 'lng': 120.20, 'lat': 30.20, 'source': '高德POI(出租信息)',
         'area': None, 'price': None, 'img': None},
        {'name': '齐全但远', 'lng': 120.60, 'lat': 30.60, 'source': '58同城(在租)',
         'area': 45, 'price': 9000, 'precise': True, 'img': 'http://x/1.jpg'},
        {'name': '齐全且近', 'lng': 120.201, 'lat': 30.201, 'source': '58同城(在租)',
         'area': 40, 'price': 8000, 'precise': True, 'img': 'http://x/2.jpg'},
        {'name': '有面积无租金', 'lng': 120.21, 'lat': 30.21, 'source': '58同城(在租)',
         'area': 50, 'price': None, 'img': None},
    ]
    kept = _rank_candidates([dict(c) for c in cands], 120.2, 30.2)
    order = [c['name'] for c in kept]
    check(len(kept) == 4, f'缺字段的候选**不被丢弃**（4 个都留），实际 {len(kept)}')
    check(order[:2] == ['齐全且近', '齐全但远'],
          f'完整度高的排前面、同档按距离近的在前，实际 {order}')
    check(order[-1] == '缺面积缺租金', f'最缺字段的排最后，实际 {order}')
    check([c['i'] for c in kept] == [1, 2, 3, 4], '重编号 1..N')
    check(all('_dist' not in c for c in kept), '内部字段 _dist 不泄漏给前端')

    many = [{'name': f'S{i}', 'lng': 120.2 + i * 0.001, 'lat': 30.2, 'source': '58同城(在租)',
             'area': 40, 'price': 8000, 'precise': True, 'img': 'http://x/i.jpg'}
            for i in range(20)]
    kept = _rank_candidates(many, 120.2, 30.2)
    check(len(kept) == CAND_TOTAL, f'20 个候选截断到 {CAND_TOTAL}，实际 {len(kept)}')
    check(kept[0]['name'] == 'S0', f'最近的在最前，实际 {kept[0]["name"]}')
    check(len({c['name'] for c in kept}) == CAND_TOTAL, '截断后无重复')


# =============================================================== §5 三态
def s5():
    sect('§5 租金/面积三态（measured / derived / unavailable）—— 用户确认口径的实现')
    SHOPS = [
        {'title': '沿街店铺 A', 'loc': '滨江-四桥南', 'price': 8000, 'area': 40},
        {'title': '沿街店铺 B', 'loc': '滨江-四桥南', 'price': 12000, 'area': 50},
        {'title': '沿街店铺 C', 'loc': '滨江-浦沿', 'price': 6000, 'area': 40},
        {'title': '沿街店铺 D', 'loc': '滨江-长河', 'price': 20000, 'area': 50},
        {'title': '沿街店铺 E', 'loc': '滨江-西兴', 'price': 10000, 'area': 50},
        {'title': '食堂档口 F', 'loc': '滨江-浦沿', 'price': 3000, 'area': 30},
    ]
    # 6 个样本单价：100,150,200,200,240,400 -> P25=150, P75=240, 中位单价=200, 中位面积=45
    cands = [
        {'name': 'A实测', 'lng': 120.20, 'lat': 30.20, 'source': '58同城(在租)',
         'area': 45, 'price': 9000, 'img': 'http://x/a.jpg', 'precise': True},
        {'name': 'B缺租金', 'lng': 120.21, 'lat': 30.21, 'source': '58同城(在租)',
         'area': 45, 'price': None, 'img': None, 'precise': True},
        {'name': 'C缺两者', 'lng': 120.30, 'lat': 30.30, 'source': '58同城(在租)',
         'area': None, 'price': None, 'img': None, 'precise': False},
    ]
    got = _fill_field_states([dict(c) for c in cands], SHOPS, '杭州滨江', '奶茶')
    A, B, C = got
    check(A['rent_state'] == 'measured' and A['area_state'] == 'measured',
          'A：列表实测 -> measured', f"{A['rent_state']}/{A['area_state']}")
    check(A['price'] == 9000 and A['area'] == 45, 'A：实测值不被推算覆盖')
    check(B['rent_state'] == 'derived', f"B：缺租金 -> derived，实际 {B['rent_state']}")
    check(B['price'] == round(200.0 * 45),
          f"B：推算租金 = 中位单价×面积 = {round(200.0 * 45)}，实际 {B['price']}")
    check(B.get('rent_band') == (round(150.0 * 45), round(240.0 * 45)),
          f"B：推算值必须带参考带区间，实际 {B.get('rent_band')}")
    check(B['area_state'] == 'measured' and B['area'] == 45, 'B：面积实测不动')
    check(C['area_state'] == 'derived' and C['area'] == 30,
          f"C：缺面积 -> 用品类标准面积(奶茶=30)，实际 {C['area']}（{C['area_state']}）")
    check('品类标准面积' in str(C.get('area_source')),
          f"C：面积推算来源必须写清，实际 {C.get('area_source')}")
    check(C['rent_state'] == 'derived' and C['rent_band'],
          f"C：租金推算自同一批样本，实际 {C['rent_state']} {C.get('rent_band')}")
    check(all(c.get('evidence_at') for c in got), '每个候选都带取证时间')
    check(got[0]['geo_state'] == 'precise' and got[2]['geo_state'] == 'area_level',
          'geo_state 区分"精确定位/仅区域级"')

    p('')
    p('  ⚠️ 用户决策点：缺字段的条目「能进但是显著标注」，且**推算必须可回溯**')
    for c in got:
        if c['rent_state'] == 'derived':
            check(bool(c.get('rent_source')) and '参考带' in c['rent_source'],
                  'derived 必须给出推算依据（否则用户无法判断可信度）', c['rent_source'])
        if c['rent_state'] == 'unavailable':
            check(c.get('rent_source') is None, 'unavailable 不得编造来源')

    p('')
    p('  无样本兜底时（本地库/高德条目且抓取失败）-> 一律 unavailable，不得静默补值')
    lone = [{'name': '兜底点', 'lng': 120.2, 'lat': 30.2, 'source': '本地数据库(兜底)',
             'area': None, 'price': None, 'img': None, 'precise': False}]
    got2 = _fill_field_states(lone, [], '杭州滨江', '不存在的品类')
    check(got2[0]['rent_state'] == 'unavailable' and got2[0]['area_state'] == 'unavailable',
          f"两者都不可得，实际 {got2[0]['rent_state']}/{got2[0]['area_state']}")
    check(got2[0]['price'] is None and got2[0]['area'] is None,
          '不可得时 price/area 必须保持 None（**绝不写 0 或 8000**）')

    p('')
    p('  cand_state_brief：给用户看的一句话，三档计数必须恰好等于候选总数')
    mixed = [dict(c) for c in got2] + [dict(c) for c in got]   # 含 1 家 unavailable
    brief = cand_state_brief(mixed)
    p(f'    「{brief}」')
    nums = [int(x) for x in re.findall(r'(\d+) 家', brief)]
    check(sum(nums) == len(mixed),
          f'三档计数之和 == 候选数（{sum(nums)} vs {len(mixed)}）—— 重叠会让用户以为漏了几家')
    check('不出经营评分' in brief,
          '**有缺字段的批次**必须明说那几家不出经营评分（否则用户会等一个永远不会出的分数）')


# =============================================================== §6 参考带
def s6():
    sect('§6 band_from_samples：复用**同一次抓取的样本**算参考带（不重抓一遍 58）')
    from engine.negotiation import band_from_samples
    SHOPS = [
        {'title': f'店铺{i}', 'loc': '滨江', 'price': p_, 'area': 40}
        for i, p_ in enumerate([4000, 6000, 8000, 8000, 9600, 16000])
    ]
    b = band_from_samples(SHOPS, scope='杭州滨江')
    check(b is not None, '6 个样本 -> 出参考带')
    if b:
        check(b['样本数'] == 6, f"样本数 {b['样本数']}")
        check(b['参考带'] == (round(150.0, 1), round(240.0, 1)),
              f"P25~P75 = 150~240，实际 {b['参考带']}")
        check(b['中位单价'] == 200.0, f"中位单价 {b['中位单价']}")
        check(b['范围'] == '杭州滨江' and '非商圈' in b['口径'],
              '口径声明必须点明"非商圈"', b['口径'])
        check('不到商圈' in b['可比性声明'] and '不可复现' in b['可比性声明'],
              '可比性声明必须含"不到商圈"与"不可复现到个位数"（答辩口径）')
        check(re.search(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}', b.get('抓取时间') or '') is not None,
              f'带取证时间（推算值必须可回溯），实际 {b.get("抓取时间")!r}')
        check(b['参考带'][0] <= b['中位单价'] <= b['参考带'][1], '中位落在带内')
    check(band_from_samples(SHOPS[:2], scope='杭州滨江') is None,
          '样本 < 3 条 -> None（不足就不给，不硬算）')
    check(band_from_samples([], scope='杭州滨江') is None, '空样本 -> None')
    check(band_from_samples([{'title': 'x', 'price': None, 'area': None}]) is None,
          '无租金/面积的样本被排除后不足 -> None')
    check('def rent_benchmark' in _read('src/engine/negotiation.py')
          and 'def band_from_samples' in _read('src/engine/negotiation.py'),
          '两个口径都保留：rent_benchmark 自带抓取，band_from_samples 不抓')


# =============================================================== §7 详情页解析
def s7():
    sect('§7 58 详情页补全（诉求④的"去找更多数据"）—— 纯解析逻辑离线真跑')
    from agent.rental58 import (_detail_url_of, _needs_detail, _rent_from_detail,
                                _area_from_detail, _addr_from_detail)
    check(RENTAL58_DETAIL is True, '详情页补全已开启（RENTAL58_DETAIL）')
    check('def fetch_details' in R58, 'fetch_details 已实现')
    # ⚠️ 这条必须看**原文**：`_CARDS_JS` 是 `"""..."""` 形式的三引号**字符串**，
    # 去注释步骤会把整段 JS 一起剥掉（它分不清"文档串"和"三引号字符串"）。
    # 断言"JS 里真的取了 href"就只能在原文上做。
    check("const a = e.querySelector('a[href]')" in R58_RAW and 'href: href' in R58_RAW,
          '列表卡片的 JS 里真的抽了 href（详情页入口）')
    check("_detail_url_of(row.get('href'))" in R58,
          'href 经 _detail_url_of 过滤后才存成 detail_url')
    check('channel=' in _fn_body(R58, '_fetch_details_async'),
          '详情页并发沿用 channel=chrome（本机默认 launch 会找不到 chromium）')

    check(_detail_url_of('https://hz.58.com/shangpu/8263924x.shtml') is not None,
          '详情 url 认出')
    check(_detail_url_of('https://hz.58.com/shangpu/') is None, '列表页不算详情')
    check(_detail_url_of('javascript:void(0)') is None, 'javascript 伪链不算')
    check(_needs_detail({'area': None, 'title': '店面', 'loc': '滨江'}) is True,
          '缺面积 -> 值得抓详情页')
    check(_needs_detail({'area': 45, 'title': '江陵路88号店面', 'loc': '滨江'}) is False,
          '有面积+有门牌 -> 不抓（省时间）')
    check(_needs_detail({'area': 45, 'title': '沿街旺铺', 'loc': '滨江'}) is True,
          '"只有区域定位" -> 抓（这就是诉求④的那批铺子）')
    check(_needs_detail({'area': 45, 'title': '沿街旺铺', 'loc': '滨江-四桥南'}) is False,
          'loc 有第二段可定位 -> 不抓')
    check(_area_from_detail('建筑面积：58㎡') == 58, '详情页面积')
    check(_area_from_detail('附近 3000㎡大卖场') is None,
          '无"面积"关键词 -> None（防侧栏推荐位串数）')
    check(_rent_from_detail('月租：8000元/月') == 8000, '详情页月租（关键词锚定）')
    check(_rent_from_detail('租金：1.6万/月') == 16000, '万/月')
    check(_rent_from_detail('单价 2.5元/㎡/天') is None, '只有单价 -> 不编月租')
    check(_rent_from_detail('押二付三\n租金：9500元/月\n推荐铺 20000元/月') == 9500,
          '首屏参数区优先（推荐位不抢）')
    check(_addr_from_detail('位置 在东站德胜路某某嘉苑，商铺全部是一楼')
          == '东站德胜路某某嘉苑', '长句截到第一个标点并去虚词（否则 geocode 必失败）',
          repr(_addr_from_detail('位置 在东站德胜路某某嘉苑，商铺全部是一楼')))
    check(_addr_from_detail('位置：滨江核心商圈') is None, '非地址文字不认')

    p('')
    p('  data 层纪律：详情页补全**只补不覆盖**，抓不到就保持原值')
    body = _fn_body(R58, 'def fetch_details(')
    check("if not it.get('area'):" in body and "if not it.get('price'):" in body,
          '只在缺失时才填（已有值一概不动）')
    check('detail_conflict' in body, '与已有值冲突 >30% 记 conflict 而不采信')
    check('returns items' not in body, '')


# =============================================================== §8 不出分纪律
async def s8():
    sect('§8 「缺租金/面积一律不出经营评分」—— 用户确认的决策点，钉死不许回退')
    p('  ⚠️ 断言只跑在**去注释**文本上：本项目习惯把"被否定的旧写法"写进注释解释为什么删，')
    p('     拿原文断言"该写法已不存在"，注释本身就会打倒断言（这是本项目反复吃过一次的亏）。')
    check('or 8000' not in GRAPH, '代码里不再有 `or 8000` 这类静默默认值')
    check("rent = state.get('rent') or 8000" not in GRAPH,
          'analyze_node 的静默默认租金已从代码里删除')
    for fn in ('async def analyze_node(', 'async def select_shop_node(',
               'async def reverse_match_node('):
        body = strip_comments(_fn_body(GRAPH, fn), 'py')
        check('8000' not in body, f'{fn[:-1].replace("async def ", "")} 函数体内无任何 8000 兜底')
    check(_read('src/agent/agent_graph.py').count('or 8000') >= 1,
          '原文里仍保留"旧写法是什么"的说明注释（供后人理解为什么不能改回去）')

    # analyze_node 缺租金 -> 早返回、不跑引擎（此分支不打任何网络）
    r = await analyze_node(mk('分析一下', category='奶茶', address='杭州滨江',
                              rent=None, area=45, phase='have_shop'))
    msg = (r['messages'] or [])[-1]['content']
    check(r.get('phase') == 'have_shop' and '经营评分' not in str(r.get('result')),
          '缺月租 -> 不进评分引擎、无 result')
    check('月租' in msg and '不会替你猜' in msg, '明确告知"不替用户猜"', msg.replace('\n', ' ')[:60])
    r2 = await analyze_node(mk('分析一下', category='奶茶', address='杭州滨江',
                               rent=9000, area=None, phase='have_shop'))
    msg2 = (r2['messages'] or [])[-1]['content']
    check('面积' in msg2 and r2.get('result') is None, '缺面积 -> 同样不出分')

    p('')
    p('  select_shop_node：三态落进 state，且对用户说清楚口径')
    base = {'messages': [{'role': 'user', 'content': '选1'}], 'phase': 'select_shop',
            'hooks': {'steps': []}, 'category': '奶茶'}
    c_una = {'name': '某铺', 'address': '杭州滨江某路', 'lng': 120.2, 'lat': 30.2,
             'source': '高德POI(出租信息)', 'area': None, 'price': None, 'precise': True,
             'rent_state': 'unavailable', 'area_state': 'unavailable'}
    r3 = await select_shop_node({**base, 'candidates': [c_una], 'place_first_mode': True})
    m3 = (r3['messages'] or [])[-1]['content']
    check(r3.get('rent') is None and r3.get('rent_state') == 'unavailable',
          '不可得 -> state.rent 保持 None（不得回落到 8000）', str(r3.get('rent')))
    check('不出经营评分' in m3, '文案必须明说本次不出经营评分', m3.replace('\n', ' ')[:80])
    check(r3.get('phase') == 'reverse_match',
          '入口 B 选中 -> 直接四品类反推（不再反问品类）', str(r3.get('phase')))

    c_der = {'name': '某铺', 'address': '杭州滨江某路', 'lng': 120.2, 'lat': 30.2,
             'source': '58同城(在租)', 'area': 45, 'price': 9000, 'precise': True,
             'rent_state': 'derived', 'area_state': 'measured',
             'rent_band': (6750, 10800), 'rent_source': '同区挂牌参考带推算(P25~P75, n=6)'}
    r4 = await select_shop_node({**base, 'candidates': [c_der], 'place_first_mode': True})
    m4 = (r4['messages'] or [])[-1]['content']
    check(r4.get('rent_state') == 'derived' and r4.get('rent_band') == (6750, 10800),
          '推算值连同区间一起进 state', str(r4.get('rent_band')))
    check('推算值' in m4 and '6,750' in m4,
          '必须显著标注"推算值"并给出参考带', m4.replace('\n', ' ')[:90])

    c_me = dict(c_der, rent_state='measured', price=9000)
    c_me.pop('rent_band')
    r5 = await select_shop_node({**base, 'candidates': [c_me]})
    check(r5.get('rent_state') == 'measured' and r5.get('phase') == 'collect_brand',
          '非 place_first + 奶茶未定品牌 -> 先收品牌', str(r5.get('phase')))

    p('')
    p('  interpret_node：推算口径必须写进解读（改造前写的是"按默认 8000"）')
    interp = _read('src/agent/agent_graph.py')
    check('按默认' not in strip_comments(interp, 'py'),
          '不再出现"按默认8000测算"这类话术')
    check('_rent_caliber' in GRAPH and '_area_caliber' in GRAPH,
          '解读层显式区分租金/面积口径')
    check("rent_state == 'derived'" in GRAPH and 'rent_band' in GRAPH,
          'derived 时把参考带一起交给解读层')


# =============================================================== §9 前端
def s9():
    sect('§9 前端：三态标签 + 候选网格自适应（15 家要排得开）')
    check('function candStateTag(' in JS, 'candStateTag 已定义')
    check('class="zl-tag warn">推算' in JS and 'class="zl-tag mute">未标' in JS,
          '两类标签的**实际标签串**都对（推算 / 未标）')
    body = _fn_body(JS, 'function renderCandidates(')
    check('candStateTag(' in body and 'area_state' in body and 'rent_state' in body,
          '候选卡片渲染里接了标签，且用的是后端给的状态字段')
    check('auto-fill' in JS and 'minmax(' in JS,
          'cand-grid 改为自适应列（15 家不会挤成一条）')
    check('--zl-tag-warn' in JS and '--zl-tag-mute' in JS, '新增两个标签色变量')
    check('#zl-right .zl-tag.warn{color:var(--zl-tag-warn)' in JS
          and '#zl-right .zl-tag.mute{color:var(--zl-tag-mute)' in JS,
          '标签样式真的引用了变量（写了变量但没引用 = 白写）')
    check('html:not(.dark)' in JS and '--zl-tag-warn:' in JS,
          '浅色主题下也定义了这两组色（否则浅色主题看不清）')
    check('var(--zl-warn-tx)' in _fn_body(JS, '#zl-right .cand-warn') or
          'var(--zl-warn-tx)' in JS,
          '警示文字用主题感知变量（浅色主题下硬编码亮黄会看不清）')
    check('rent_band' in APP and 'rent_state' in APP, '后端卡片载荷带三态字段')
    check('rent_state' in APP, '载荷确实带上了三态（不是前端硬猜）')
    check('选中后自动按四品类反推' in APP, 'place_first 时 hint 说明选中后做什么')


# =============================================================== §10 图接线
def s10():
    sect('§10 图接线：place_first 节点 + search_rental 直接结束')
    check("add_node('place_first', collect_place_node)" in GRAPH
          or "add_node('place_first'" in GRAPH, 'place_first 节点已注册')
    check("'place_first': 'place_first'" in GRAPH, 'classify 有 place_first 出边')
    check("'search_rental' if state.get('phase') == 'search_rental'" in GRAPH,
          'place_first -> search_rental 条件边存在')
    check("workflow.add_edge('search_rental', END)" in GRAPH,
          'search_rental 直接结束本轮')
    check("add_edge('search_rental', 'select_shop')" not in GRAPH,
          '旧的 search_rental->select_shop 已拆掉'
          '（否则同轮 select_shop 会再喊一句"请回复序号"，把候选摘要顶掉）')
    check("'reverse_match' if state.get('phase') == 'reverse_match'" in GRAPH,
          'select_shop -> reverse_match 分岔存在（入口 B 选中后直接反推）')
    for f in ('place_first_mode', 'rent_state', 'area_state', 'rent_band'):
        check(f in GRAPH, f'state 透传字段 {f} 存在')
    try:
        import inspect
        from agent.state import AgentState
        keys = set(getattr(AgentState, '__annotations__', {}) or {})
        for f in ('place_first_mode', 'rent_state', 'area_state', 'rent_band'):
            check(f in keys, f'AgentState 声明了 {f}')
    except Exception as e:
        check(False, 'AgentState 可导入且含新字段', f'{type(e).__name__}: {e}')


# =============================================================== §11 品类不再被反问
async def s11():
    sect('§11 诉求①：**品类缺失时永不主动索要**（品类是结论，不是前提）')
    p('  用户原话：「当我说好我想在哪开店时你就直接问我品类了呢？'
      '这不应该是你最后得出的结论吗？」')
    p('  改造前有两条路会问品类：① no_shop 收集环节；② 有铺子但没品类（have_shop）。')
    p('')

    from agent.agent_graph import collect_info_node

    p('  (a) 只有地点、没品类 -> 直接去搜铺源，且置 place_first_mode')
    r = await collect_info_node(mk('我想在杭州滨江开店', phase='no_shop',
                                   address='杭州滨江'))
    msg = (r['messages'] or [{}])[-1].get('content', '') if r.get('messages') else ''
    check(r.get('phase') == 'search_rental',
          f'no_shop + 有地点 + 无品类 -> search_rental，实际 {r.get("phase")}')
    check(r.get('place_first_mode') is True,
          '必须置 place_first_mode（选中后才会走四品类反推，而不是回头问品类）')
    check('品类' not in msg, '本轮的追问/回复里不得出现"品类"二字', msg.replace('\n', ' ')[:60])

    p('')
    p('  (b) 连地点都没有 -> 只问地点，**绝不问品类**')
    r2 = await collect_info_node(mk('我想开个店', phase='no_shop'))
    m2 = (r2['messages'] or [{}])[-1].get('content', '')
    check('品类' not in m2 and r2.get('phase') == 'no_shop',
          '追问文案只问区域，不含"品类"', m2.replace('\n', ' ')[:60])
    check(any('区域' in x for x in (r2.get('missing_info') or [])),
          'missing_info 只列地点', str(r2.get('missing_info')))
    check(not any('品类' in x for x in (r2.get('missing_info') or [])),
          'missing_info 里不得有品类（改造前正是它让 UI 弹出"想开什么品类"输入框）')

    p('')
    p('  (c) 有具体铺子（地址+月租）但没品类 -> 直接四品类反推，不问品类')
    r3 = await collect_info_node(mk('杭州滨江江陵路88号，月租1万', phase='have_shop',
                                    address='杭州滨江江陵路88号', rent=10000))
    m3 = (r3['messages'] or [{}])[-1].get('content', '') if r3.get('messages') else ''
    check(r3.get('phase') == 'shop_first',
          f'有铺无品类 -> shop_first（定位后反推），实际 {r3.get("phase")}')
    check((r3.get('shop_first_data') or {}).get('rent') == 10000,
          '已收集到的月租必须带过去，不能在反推环节再问一遍')
    check('品类' not in m3, '不得反问品类', m3.replace('\n', ' ')[:60])

    p('')
    p('  (d) 有铺子但地址/月租不全 -> 只问缺的那两项，仍不问品类')
    r4 = await collect_info_node(mk('我租了个铺子', phase='have_shop'))
    m4 = (r4['messages'] or [{}])[-1].get('content', '')
    check('品类' not in m4, '追问不含品类', m4.replace('\n', ' ')[:60])
    check('月租金' in m4 or '位置' in m4, '问的是地址/月租', m4.replace('\n', ' ')[:60])

    p('')
    p('  (e) 静态钉死：全图不得再出现"想开什么品类"的追问')
    check('想开什么品类' not in GRAPH, '代码里不再有"想开什么品类"的追问')
    check('品类（奶茶/甜品/早餐/便利店）' not in GRAPH,
          'missing_info 不再把"品类（奶茶/甜品/早餐/便利店）"塞进追问')
    check("'shop_first': 'shop_first'," in GRAPH,
          'collect_info -> shop_first 的条件边存在（无品类有铺子时要用到）')

    p('')
    p('  (f) 只有**用户自己说了品类**才走 A 流程（先品类）')
    for t in ('我想开奶茶店', '滨江开个便利店', '想开甜品店'):
        ph = await phase_of(t)
        check(ph == 'no_shop', f'有品类 -> A 流程 no_shop，实际 {ph}：{t}')


# =============================================================== §12 兜底退出
def s12():
    sect('§12 诉求②：兜底 POI **一律不进候选**（那不是房源）')
    p('  根因：候选不足时有两级兜底 ——')
    p('    ① 高德 POI：关键词 f"{category}出租"，品类=奶茶就是"奶茶出租"')
    p('       -> 返回的是**正在营业的奶茶店**（用户原话："你把正在开的奶茶店的商铺地址给我干嘛"）')
    p('    ② 本地库：query_within(\'商圈\',\'办公\') -> 商圈/写字楼点位，既非房源也无租金面积')
    p('  用户决策：一律不出，**接受候选数可能不足 15**。')
    p('')
    body = _fn_body(GRAPH, 'async def search_rental_node(', maxlen=20000)
    check(bool(body), '取到 search_rental_node 函数体（正则没匹配到就是断言失效，必须报错）')
    check('search_poi(' not in body, '函数体里不再调用高德 POI 搜索')
    check('query_within(' not in body, '函数体里不再调用本地库兜底')
    check("'高德POI" not in body and '高德POI(出租信息)' not in GRAPH,
          '不再产出"高德POI"来源的候选')
    check('本地数据库(兜底)' not in GRAPH, '不再产出"本地数据库(兜底)"来源的候选')
    check('CAND_LIMIT_FALLBACK' not in GRAPH, '兜底上限常量已删除（留着会被误用）')
    check("'（含非实时在租的兜底点位）'" not in GRAPH,
          '文案里不再有"含兜底点位"的说法')
    check(GRAPH.count("_st.stop('58抓取+候选定位')") == 1,
          '阶段计时只 stop 一次（删兜底时容易留下第二个 stop，导致耗时账本错乱）')

    p('')
    p('  取数失败 vs 真的没有：三种情况文案必须**各不相同**（不许混成一句"没搜到"）')
    check('取数失败' in GRAPH and '确实没有搜到在租商铺' in GRAPH,
          '两种空结果各有独立文案')
    check('不是抓取失败' in GRAPH, '真·无房源时明说"不是抓取失败"（区别"系统没数据"）')
    check('不足 15 家' in GRAPH and 'CAND_TOTAL' in GRAPH,
          '候选数 < 15 时如实说明"真房源就这么多"，不拿兜底凑数')


# =============================================================== §13 房源性质+定位分级
def s13():
    sect('§13 诉求③：房源性质（出租/转让）+ 地址三级显示')
    from agent.rental58 import _deal_type
    p('  用户决策：58 里"正在营业中转让"的条目**要算**（"3要算"），但必须能一眼分辨。')
    p('')
    check(_deal_type('滨江区沿街商铺出租') == '出租', '出租 -> 出租')
    check(_deal_type('旺铺招租 免中介') == '出租', '招租 -> 出租')
    check(_deal_type('奶茶店转让 设备齐全') == '转让', '转让 -> 转让')
    check(_deal_type('门面转租 可续租') == '转让', '转租 -> 转让')
    check(_deal_type('转让·也可续租') == '转让',
          '同时含"转让"与"租" -> 判转让（本质是转店，谈判对象是现任租户）')
    check(_deal_type('滨江空铺 面积50平') == '', '中性词不猜（判不出就不标）')
    check(_deal_type('') == '' and _deal_type(None) == '', '空输入不报错')

    p('')
    p('  data 层：deal 在**区域过滤之前**算（否则过滤掉的就白算了）')
    rb = _fn_body(R58, 'def fetch_shops(')
    check("item['deal'] = _deal_type(full)" in rb, 'fetch_shops 里给每条打 deal 标记')
    check(rb.find("item['deal'] = _deal_type(full)") < rb.find('if area_filter'),
          'deal 标记必须在区域过滤**之前**（顺序反了会漏标）')

    p('')
    p('  图层：候选带 deal + addr_level，层级在定位阶梯的每一级都记下来')
    add_body = _fn_body(GRAPH, 'def add_cand(')
    for k in ("'deal'", "'addr_level'"):
        check(k in add_body, f'add_cand 的候选结构里有 {k}')
    sb = _fn_body(GRAPH, 'async def search_rental_node(', maxlen=20000)
    for lvl in ("lvl = 'door'", "lvl = 'building'", "lvl = 'street'", "lvl = 'area'"):
        check(lvl in sb, f'定位阶梯记录了 {lvl}')
    check("lvl = 'area'" in sb and 'target_lng, target_lat\n' in sb,
          '回落区域中心那一步把层级改成 area（不假装精确）')
    check('add_cand(' in sb and 'addr_level=lvl' in sb and 'deal=' in sb,
          '候选创建时把 deal / addr_level 传下去')
    check("c['addr_level'] = c.get('addr_level') or ('door' if c.get('precise') else 'area')" in GRAPH,
          '_fill_field_states 给缺失的补默认层级（旧数据/兜底路径不会漏）')

    p('')
    p('  UI 层：四级文案齐备，且**区域级必须写"无门牌"**')
    check('ADDR_LEVEL_TXT' in JS, 'ADDR_LEVEL_TXT 映射表存在')
    for k in ('door:', 'building:', 'street:', 'area:'):
        check(k in JS, f'映射表含 {k}')
    check('区域级·无门牌' in JS,
          '区域级文案带"无门牌"（用户抱怨的就是"有些又是区域级定位"分不出来）')
    jb = _fn_body(JS, 'function renderCandidates(')
    check("c.deal === '转让'" in jb, '转让铺在卡片上单独标出')
    check('房东招租' in jb, '招租铺标签与转让区分（不再笼统写"在租"）')
    check('转让费' in jb and '原租约' in jb,
          '转让铺给出"问什么"的提示（转让费/原租约/设备），否则用户会拿它直接比租金')
    # 卡片是纯文本渲染：markdown 的 ** 会原样露星号（label 踩过这个坑）
    tfer = jb[jb.find("c.deal === '转让'"):]
    check('**' not in tfer[:240], '转让提示文案里不带 markdown 星号（卡片不解析 md）')

    p('')
    p('  房源性质标签必须用**独立 class**（dl-tr/dl-rt），不许复用三态标签的 warn/ok')
    p('  —— 三态探针（live_ui_probe §11）正是靠 .zl-tag.warn 数「推算」的，')
    p('     复用会让转让铺被误统计成推算值，把数据可信度口径搅浑。')
    check('zl-tag dl-tr' in jb and 'zl-tag dl-rt' in jb,
          '转让/招租用 dl-tr / dl-rt 两个独立 class')
    check('zl-tag warn">转让' not in jb and 'zl-tag ok">房东招租' not in jb,
          '没有复用 warn / ok（复用会与三态标签撞车）')
    check('zl-tag.dl-tr' in JS and 'zl-tag.dl-rt' in JS, '两条对应的 CSS 规则都在')
    check("c.deal === '出租'" in jb,
          '只在 deal 明确为"出租"时才标"房东招租"，判不出的第三态**不打标签**'
          '（实机抓到过：15 家里 11 家判不出却全标了"房东招租"）')
    check('没写明性质' in GRAPH,
          '聊天区的房源性质构成要把第三态说出来，不能只报"房东招租 + 转让"'
          '（只报两项时，用户会把没打标签的也读成招租）')

    p('')
    p('  后端载荷：前端不做推断，deal/addr_level 由后端给')
    check("'deal': c.get('deal')" in APP, '候选载荷带 deal')
    check("'addr_level': c.get('addr_level')" in APP, '候选载荷带 addr_level')
    check('区域级·无门牌' not in APP, '文案只在 JS 一处定义（避免两处不一致）')


# =============================================================== §14 加盟费下限
async def s14():
    sect('§14 诉求④/⑦：加盟费单列 + 填投入时提示 + **显示后放行**的软下限')
    p('  用户拍板：⑦ 下限取「单列加盟费」，低于门槛**显示后放行**（不硬拦）。')
    p('')
    from engine.brands import get_join_fee, get_franchise_info, FRANCHISE_INFO
    jf = get_join_fee('蜜雪冰城')
    check(jf and jf['fee'] == 11000, f'蜜雪加盟费单列 = 11000，实际 {jf and jf["fee"]}')
    check(jf and jf['unit'] == '元/年', f'单位是"元/年"（加盟费是按年续缴），实际 {jf and jf["unit"]}')
    check(jf and jf['band'] == (7000, 11000), '带公开口径区间')
    check(jf and jf['tier'] in ('B', 'C'), '带可信度分级（不许当精确值）')
    check(jf and jf['text'] and '11,000' in jf['text'] and '区间' in jf['text'],
          '直接可显示的文案里同时有值与区间', jf and jf['text'])
    # 本项目铁律：外部数据必须「来源 + 取证时间」可溯源（答辩会被问"这数什么时候查的"）
    check(jf and jf.get('asof') == '2026-09-17',
          f'带取证时间，实际 {jf and jf.get("asof")}')
    check(jf and jf.get('src') and len(jf['src']) > 8,
          '带来源', jf and jf.get('src'))
    check(jf and '截至 2026-09-17' in jf['text'],
          '取证时间也进可显示文案（用户看得到这数是几时核的）')

    p('')
    p('  文案不得自相重复：`jf["text"]` 本身就以"加盟费"开头，拼提示时不能再写一遍')
    p('  —— 实机曾渲染成「蜜雪冰城 加盟费 加盟费 ¥11,000」（只有实机能发现这类观感缺陷）')
    check('加盟费 加盟费' not in APP, '后端 note 没把"加盟费"念两遍')
    check('加盟费 加盟费' not in JS, '前端下限提示也没念两遍')

    p('')
    p('  ⚠️ 最关键的一条：**「没查到」不等于「免费」**；而「明确不收」也不是「没查到」')
    p('  —— 加盟费必须是**三态**（amount / none / unknown），瑞幸入表时暴露了这个缺口。')
    jf0 = get_join_fee('春莱')
    check(jf0 is not None and jf0['fee'] is None,
          f'查不到口径的品牌 -> fee 必须是 None（不是 0），实际 {jf0 and jf0["fee"]}')
    check(jf0 and jf0.get('status') == 'unknown',
          f'查不到 -> status=unknown，实际 {jf0 and jf0.get("status")}')
    check(jf0 and '暂无公开加盟费口径' in jf0['text'],
          '并把"不编数据"这件事说出来，而不是静默跳过', jf0 and jf0['text'])

    p('')
    p('  第三态：**明确不收**（瑞幸）—— 0 是事实，不是"查不到"')
    from engine.brands import join_fee_status
    jfr = get_join_fee('瑞幸')
    check(jfr and jfr['fee'] == 0 and jfr.get('status') == 'none',
          f'瑞幸 fee=0 且 status=none，实际 {jfr and (jfr["fee"], jfr.get("status"))}')
    check(jfr and '明确不收加盟费' in jfr['text'] and '暂无' not in jfr['text'],
          '文案必须说"明确不收"；说"暂无公开口径"对瑞幸是**假话**', jfr and jfr['text'])
    check(jfr and '毛利' in jfr['text'],
          '同时把"按门店月毛利阶梯分成"这条**附带成本**说出来（不说 = 静默给偏乐观结论）',
          jfr and jfr['text'])
    check(bool(get_franchise_info('瑞幸').get('cost_notes')),
          'cost_notes 非空（会随"局限"一起进诊断报告）')
    check(not any(v.get('join_fee') == 0
                  for k in FRANCHISE_INFO
                  if join_fee_status(k) != 'none'
                  for v in [get_franchise_info(k) or {}]),
          '除"明确不收"的品牌外，任何品牌都不得把加盟费写成 0（0 会被读成"不收加盟费"）')

    p('')
    p('  下限守卫：无品牌/无口径 -> 不做校验（不能拿 0 去比，否则永远不触发）')
    from agent.agent_graph import _join_fee_floor, _is_floor_confirm, collect_invest_node
    check(_join_fee_floor('蜜雪冰城')[0] == 11000, '蜜雪下限 = 11000')
    check(_join_fee_floor('春莱') == (None, ''), '无口径 -> (None, "")')
    # 明确不收（瑞幸）也返回无下限 —— 但**理由相反**：不是"查不到"，是"本就不适用"。
    # 钉住它是防止有人看到 (None,'') 就把 _join_fee_floor 的 docstring 当"都是查不到"
    # 理解，进而拿它的返回值去拼用户文案（那就会对瑞幸说"暂无公开口径"）。
    check(_join_fee_floor('瑞幸') == (None, ''),
          '明确不收加盟费 -> 同样无下限（理由与"查不到"相反，别混用它的文案）')
    check(_join_fee_floor('') == (None, '') and _join_fee_floor(None) == (None, ''),
          '没选品牌 -> 不校验')
    check(_is_floor_confirm('确认') is True, '"确认"算确认')
    check(_is_floor_confirm('就按这个算') is True, '"就按这个算"算确认')
    check(_is_floor_confirm('12万') is False, '报数字**不算**确认（否则等于没校验）')
    check(_is_floor_confirm('确认，但是我想问下这个租金合理吗，周边还有没有别的选择呢') is False,
          '长句子不算确认（避免用户顺口带个"确认"就放行）')

    p('')
    p('  节点真跑：低于加盟费 -> 提示 + 停在 collect_invest；确认后 -> 照算')
    base = {'messages': [{'role': 'user', 'content': '1万'}], 'phase': 'collect_invest',
            'hooks': {'steps': []}, 'category': '奶茶', 'brand': '蜜雪冰城'}
    r = await collect_invest_node({**base, 'investment': 10000})
    m = (r['messages'] or [{}])[-1].get('content', '')
    check(r.get('phase') == 'collect_invest',
          f'低于加盟费 -> 停在 collect_invest 等确认，实际 {r.get("phase")}')
    check('加盟费' in m and '确认' in m,
          '文案要说明"低于加盟费"并给出确认方式', m.replace('\n', ' ')[:80])
    check('不会偷偷帮你改数' in m,
          '明确说"不会偷偷改数"（否则用户以为系统又替他估了）')

    r2 = await collect_invest_node({**base, 'investment': 10000,
                                    'messages': [{'role': 'user', 'content': '确认'}]})
    check(r2.get('phase') == 'analysis',
          f'确认后放行 -> analysis，实际 {r2.get("phase")}')
    m2 = (r2['messages'] or [{}])[-1].get('content', '')
    check('已确认按此口径' in m2, '放行时说明"已确认按此口径"（结论里要留痕）', m2.replace('\n', ' ')[:80])

    r3 = await collect_invest_node({**base, 'investment': 350000,
                                    'messages': [{'role': 'user', 'content': '35万'}]})
    check(r3.get('phase') == 'analysis', '高于下限 -> 直接算，不打扰用户')
    m3 = (r3['messages'] or [{}])[-1].get('content', '')
    check('已含在该投入内' in m3, '正常路径也要把口径写出来', m3.replace('\n', ' ')[:80])

    r4 = await collect_invest_node({**base, 'brand': '春莱', 'investment': 10000,
                                    'messages': [{'role': 'user', 'content': '1万'}]})
    check(r4.get('phase') == 'analysis', '无公开口径的品牌 -> 不做校验，直接算')

    p('')
    p('  口径文案：前期投入必须点明"含加盟费"（改造前没写，用户按字面填就会漏）')
    from agent.agent_graph import ask_investment_message
    am = ask_investment_message('奶茶', '蜜雪冰城')
    check('含加盟费/保证金/设备/装修/首批物料' in am, '口径写清含什么')
    check('不含房租押金' in am, '口径写清不含什么（押金不进月成本也不摊销）')
    check('加盟费' in am and '11,000' in am, '选了品牌就把加盟费提示出来')
    check('加盟费' in am and '不能低于这个数' in am, '并说明"不能低于这个数"')
    check('31.8' not in am and '流水' not in am, '不夹带别的数字')
    am2 = ask_investment_message('便利店', '')
    check('暂无公开加盟费口径' not in am2, '没品牌时不显示加盟费提示行')
    check('含加盟费' in am2, '但口径说明仍要说"含加盟费"（用户可能自己加盟）')

    p('')
    p('  前端：表单旁显示加盟费 + 第二道软校验（单位必须换算，否则校验永远不触发）')
    check("'note': inv_note" in APP and "'floor': inv_floor" in APP,
          '投资字段带上 note/floor')
    check('含加盟费/保证金/设备/装修/首批物料，不含房租押金' in APP, '表单口径说明')
    check('**' not in (APP[APP.find('inv_note = '):APP.find('inv_note = ') + 120]),
          'inv_note 是纯 HTML 文案，不能带 markdown 星号（否则星号原样显示）')
    check('function checkInvestFloor(' in JS, '前端校验函数存在')
    chk = _fn_body(JS, 'function checkInvestFloor(')
    check('* 10000' in chk,
          '⚠️ 表单投资单位是**万元**、floor 是**元** —— 必须换算，'
          '否则 11000 元被当成 11000 万，校验永远不触发（"看起来生效了"最危险）')
    check('data-acked' in chk or 'acked' in chk,
          '必须"再点一次才放行"，一次点击直接提交等于没校验')
    check("d.mode === 'invest' && !checkInvestFloor" in JS,
          '提交钩子里真的接上了（定义了不调用 = 白写）')


# =============================================================== §15 瑞幸一等公民
async def s15():
    sect('§15 瑞幸入表：既要与蜜雪/古茗**同等可用**，又**不许编**没标定的字段')
    from engine.brands import (brand_attractiveness, BRAND_S, BRAND_KEYWORDS,
                               UPLIFT, brand_uplift_detail, brand_order_value,
                               FRANCHISE_INFO)
    from engine.utilities import get_material_ratio

    p('  ① 识别：中文名 + luckin 三种大小写（本地库实测三种写法都真实存在）')
    for nm in ('瑞幸咖啡(杭州湖滨银泰in77店)', 'luckin coffee 宁波天一店',
               'Luckin Coffee(海宁银泰城店)', 'LUCKIN COFFEE 星巴克旁店'):
        b, s = brand_attractiveness(nm)
        check(b == '瑞幸' and s == 2.2, f'「{nm[:18]}」→ 瑞幸(2.2)', f'实得 {b}({s})')
    check(BRAND_S.get('瑞幸') == 2.2, 'BRAND_S[瑞幸] = 2.2（=古茗档，不是蜜雪档）')
    kws = BRAND_KEYWORDS.get('瑞幸') or []
    check('luckin' in kws and 'Luckin' in kws and 'LUCKIN' in kws,
          '关键词必须列全大小写（`kw in name` 大小写敏感，CoCo 那次踩过同一个坑）')

    p('')
    p('  ② 标定状态：v7 后瑞幸**已进 UPLIFT 且不再被 clamp 截断**')
    # 变更史（**这条断言改过两次，别照着旧版"修回去"**）：
    #   v1（83 家人工商圈）时瑞幸没有标定样本 → 断言是 `'瑞幸' not in UPLIFT`，
    #      且要求 brand_uplift_detail 返回 1.0/TIER3/ci=None/n=None。
    #   v6（2026-09-18，代理商圈口径整表重标定）后瑞幸 n=55 → 收录且进 TIER1，
    #      但点估计被常数护栏 clamp 截到 1.2500（raw 1.2992 → 收缩 1.2743 → clamp）。
    #   v7（同日，uplift 换成"品牌盲残差"消双算）后瑞幸 raw 降到 1.1736、
    #      收缩 1.1591，**不再触发 clamp** ⇒ 1.2500/1.1591 这处断言随之重标定。
    #   v8（2026-09-21，只换距离口径：直线 → 步行路网）后瑞幸 raw 1.3660、
    #      收缩 **1.3271**、n 55 → **42**，仍 TIER1 且仍不触发 clamp。
    #   旧断言若不改，门禁会**拦住这几合法的口径升级**。
    check('瑞幸' in UPLIFT, 'UPLIFT 里必须有瑞幸（v8 有 n=42 的标定样本）',
          '未收录 ⇒ 要么被回退到 v1 口径，要么标定脚本没跑')
    d = brand_uplift_detail('瑞幸咖啡(x)')
    check(d['uplift'] == 1.3271 and d['tier'] == 'TIER1' and d['n'] == 42,
          'brand_uplift_detail → 1.3271 / TIER1 / n=42（v8 值）', str(d))
    check(d['ci'] is not None and d['ci'][0] > 1.0,
          'CI 下界必须 >1.0 —— 这是 TIER1 的判定条件（区间排除 1.0）', str(d['ci']))
    # ⚠️ 2026-09-21（v8）这条判据**必须改写法**：
    #    原判据是 `UPLIFT['瑞幸'] < 1.25`，它在 v7 下成立（1.1591 < 1.25）。
    #    v8 换路网后瑞幸升到 **1.3271，越过了 1.25** —— 但它是 **TIER1 免 clamp**，
    #    所以 1.3271 是**未截断的真实收缩值**，不是被截断产物。
    #    ⇒ 原判据"值必须 < 1.25"在免 clamp 语境下**不再等价于"未被截断"**，
    #      真正的意图是"落地值不等于护栏上界（没被削平）"。改成下面这个判据。
    #    ⚠️ 同时必须出声：瑞幸现在的点估计**已越过** clamp 上界，报告里依然
    #      不许把 1.25 读成"真实上界"—— 恰恰相反，1.25 现在是个**够不到的假天花板**。
    check(abs(UPLIFT['瑞幸'] - 1.25) > 1e-9,
          f'瑞幸必须**不再**被 clamp 截断（v6 的 1.2500 是 raw 1.2992 被削平的产物，'
          f'真实收缩值 1.2743；v8 路网口径下为 {UPLIFT["瑞幸"]}）—— '
          f'截断方向是**低估**，报告里不许把 1.25 读成"真实上界"',
          f'实得 {UPLIFT["瑞幸"]}')
    if UPLIFT['瑞幸'] > 1.25:
        p(f'  ⚠️ 瑞幸 {UPLIFT["瑞幸"]} 已**越过** clamp 上界 1.25 —— TIER1 免 clamp 的'
          f'合法结果（未被截断），但它与"带 clamp 的 CI"不再自洽，见下条。')

    p('')
    p('  ③ 物料率品牌级覆盖：瑞幸 36% ≠ 奶茶品类 32%（漏了就低估成本、回本算短）')
    check(get_material_ratio('奶茶', '瑞幸') == 0.36,
          "get_material_ratio('奶茶','瑞幸') == 0.36",
          str(get_material_ratio('奶茶', '瑞幸')))
    check(get_material_ratio('奶茶') == 0.32, '不传 brand 仍是品类级 0.32（向后兼容）')
    check(get_material_ratio('奶茶', '蜜雪冰城') == 0.32, '未设覆盖的品牌仍走品类级')

    p('')
    p('  ④ 每单金额：瑞幸是**推导值**，必须与"披露值"可分辨（否则答辩一问口径就穿）')
    r = brand_order_value('瑞幸')
    mx = brand_order_value('蜜雪冰城')
    check(bool(r) and bool(mx), '两个品牌都取得到每单金额')
    if r and mx:
        check(abs(r['每单金额'] - 13.82) < 0.01, '瑞幸每单金额 = 13.82（GMV÷杯量推导）',
              str(r['每单金额']))
        check(r.get('公开值') is False,
              '瑞幸标【推导值】(公开值=False)', f"金额来源={r.get('金额来源')}")
        check(mx.get('公开值') is True,
              '蜜雪仍标【披露值】(不把两者混同)', f"金额来源={mx.get('金额来源')}")

    p('')
    p('  ⑤ 品牌成本提示必须随结论一起出去（瑞幸的毛利阶梯分成不进「月成本合计」）')
    fi = FRANCHISE_INFO.get('瑞幸') or {}
    check(fi.get('invest_ref') == 400000, '投资参考 40 万（区间中位）',
          str(fi.get('invest_ref')))
    notes = fi.get('cost_notes') or []
    check(bool(notes), 'cost_notes 非空（不静默）')
    check(any('分成' in x for x in notes), '提示里必须点明"毛利分成未计入"这件事',
          str(notes)[:70])

    p('')
    p('  ⑥ 知识库**两处表面**必须同步（改一处忘另一处是本项目高发错）')
    kb = _read('src/agent/knowledge.py')
    check(kb.count('瑞幸') >= 2, 'RAG 语料里有瑞幸专条',
          f'knowledge.py 出现「瑞幸」{kb.count("瑞幸")} 次')
    i = JS.find('var KB_THEORY')
    check(i > 0, '能在去注释文本里定位 KB_THEORY')
    js_kb = JS[i:] if i > 0 else ''
    check('瑞幸' in js_kb, '前端静态知识页 KB_THEORY 也写了瑞幸（两个表面都要改）')
    # ⚠️ 这条断言改过两次，核心不变：静态页必须与引擎**说同一套数字**，
    #    不能停在旧口径（静态页与 RAG 语料是同一事实的两处表面）。
    #    v1 要求"如实标【未标定】"；v6 改成写 v6 实测值；v7 消双算后改成写 v7 值。
    check('1.3271' in js_kb, '静态页的 UPLIFT 表已更新到 v8（瑞幸 1.3271）')
    check('1.0000' in js_kb and '0.9970' in js_kb,
          '静态页写出 v8 的蜜雪 1.0000 / 古茗 0.9970（路网口径值）')
    check('重复计入' in js_kb or '双算' in js_kb,
          '静态页**必须**写出"旧口径会重复计入品牌力 ⇒ 双算，故改成品牌盲残差"这条局限'
          '（不许只报数字不讲局限）')
    check('品牌盲' in js_kb,
          '静态页要写出新口径的名字（"品牌盲残差"），'
          '否则用户不知道 1.1591 与 v6 的 1.2500 差别在哪')

    p('')
    p('  ⑦ 加盟费三态有**两个表面**（聊天提示 / 投入表单提示），必须一起改 —— '
      '本轮实机前读代码就抓到表单那处漏了')
    # 背景：三态改造先落在 agent_graph.collect_invest_node（聊天提示），
    #       但 app_chainlit 里构造投入表单 note 的那段仍是老的 `if jf.get('fee'):`
    #       → 瑞幸 fee=0 是 falsy，会掉进 elif 分支、在表单上写
    #       「瑞幸 暂无公开加盟费口径，不做下限校验」——正是本轮修掉的那句假话。
    #       这类"改了 A 面忘了 B 面"是本项目高发错（知识库两处表面同源）。
    check('status' in APP and "== 'none'" in APP,
          "app_chainlit.py 必须按 status 三态分派（不能按 fee 真假分派）",
          '未在表单构造段发现 status 判断')
    # 反向再钉一次：用**顺序**表达"先判 status、再判 fee"这条不变式。
    # 不能用 `"jf.get('fee'):" not in APP` 这类字面断言 —— 新写法里
    # `elif jf and jf.get('fee'):` 本来就含这个子串（且 `elif` 里也带着 `if`），
    # 字面查会自己打自己。而顺序断言能真正抓住回退：一旦有人改回
    # 只写 `if jf and jf.get('fee'):`，`jf.get('status')` 就整个消失 → 必 FAIL。
    _i_st = APP.find("jf.get('status')")
    _i_fee = APP.find("jf.get('fee')")
    check(_i_st > 0 and _i_fee > _i_st,
          '三态判断（status）必须排在 fee 真假判断**之前** —— 否则瑞幸 fee=0 '
          '是 falsy，会绕过三态掉进"暂无口径"分支说假话',
          f"status 判断 @{_i_st} / fee 真假判断 @{_i_fee}")
    check(_i_st > 0 and APP.find('暂无公开加盟费口径') > _i_st,
          '"暂无公开加盟费口径"这句必须排在三态判断之后'
          '（排在前面说明它在三态之外，瑞幸会掉进去说假话）',
          f"三态判断 @{_i_st} / 暂无口径 @{APP.find('暂无公开加盟费口径')}")


# ======================= §16 UPLIFT v7 品牌盲残差（消双算，2026-09-18）
async def s16():
    sect('§16 UPLIFT v7：品牌盲残差 —— 收录面、口径纪律、双算已消，三样都要钉住')
    from engine.brands import (UPLIFT, UPLIFT_TIER, UPLIFT_CI, _UPLIFT_N)

    p('  ① 四张表必须键一致（少一个键 = UI/报告取不到 CI 或 n，静默降级成"未收录"）')
    for nm, tab in (('UPLIFT_TIER', UPLIFT_TIER), ('UPLIFT_CI', UPLIFT_CI),
                    ('_UPLIFT_N', _UPLIFT_N)):
        extra = sorted(set(tab) - set(UPLIFT))
        miss = sorted(set(UPLIFT) - set(tab))
        check(set(tab) == set(UPLIFT), f'{nm} 与 UPLIFT 同键',
              f'多={extra} 少={miss}')

    p('')
    p('  ② 值域：点估计必须落在自己的 CI 内；CI 必须夹在 clamp(0.80,1.25) 内')
    # ⚠️ 2026-09-21（v8）：**这一天真的来了**，见上面的伏笔注释。
    #    3 个 TIER1（春莱 1.5177 / 奈雪 1.3632 / 瑞幸 1.3271）的点估计
    #    **全部越过** CI 上界 1.25。
    #    根因不是算错，是**两套口径打架**：
    #      · 点估计：TIER1 **免 clamp** ⇒ 用真实收缩值（可以 > 1.25）
    #      · CI      ：按 recalibrate_uplift_v3.py 的既定做法，判级与 CI 一律
    #                  **带 clamp** 计算（为了与 v1/v6 逐位可比）⇒ 上界被削到 1.25
    #    ⇒ 免 clamp 的点估计自然会捅破带 clamp 的 CI。这是**设计决定的自洽性裂缝**，
    #      需要裁决（改 TIER1 判据要求 CI 不被截断 / 或给 TIER1 也算免 clamp 的 CI），
    #      门禁**不替这个决定**，只把它如实钉住并往下传。
    #    分两段表达：
    #      (a) TIER2/TIER3 受护栏约束 ⇒ 必须落在 CI 内（这条不许放水）
    #      (b) TIER1 允许越界，但**只允许**因"CI 上界被削到 1.25"这一种原因越界
    bad23 = [b for b in UPLIFT
             if UPLIFT_TIER[b] != 'TIER1'
             and not (UPLIFT_CI[b][0] <= UPLIFT[b] <= UPLIFT_CI[b][1])]
    check(not bad23, 'TIER2/TIER3 的点估计都落在自己的 CI 内（它们受 clamp 护栏约束）',
          str(bad23))
    _oob = sorted(b for b in UPLIFT if UPLIFT[b] > UPLIFT_CI[b][1])
    _bad1 = [b for b in _oob
             if not (UPLIFT_TIER[b] == 'TIER1' and abs(UPLIFT_CI[b][1] - 1.25) < 1e-9)]
    check(not _bad1,
          '点估计越过 CI 上界**只允许**发生在 TIER1，且 CI 上界必须恰好是 clamp 天花板 1.25'
          '（免 clamp 的已知代价；其他任何越界都是真错）',
          str(_bad1))
    if _oob:
        p(f'  ⚠️ 已知裂缝（待裁决）：{len(_oob)} 个 TIER1 的点估计越过"带 clamp 的 CI"上界 ——')
        for b in _oob:
            p(f'        {b}：点估计 {UPLIFT[b]} vs CI 上界 {UPLIFT_CI[b][1]}'
              f'（TIER1 免 clamp，故未被截断）')
    out = [b for b in UPLIFT
           if UPLIFT_CI[b][0] < 0.80 - 1e-9 or UPLIFT_CI[b][1] > 1.25 + 1e-9]
    check(not out, 'CI 都夹在 clamp(0.80,1.25) 内（越界说明标定脚本漏了 clamp）',
          str(out))

    p('')
    p('  ③ v7 的规模与分级（钉住整表重标定 + 消双算的结果，防静默回退）')
    check(len(UPLIFT) == 28, 'v7 收录 28 个品牌（v1 是 9 个）', str(len(UPLIFT)))
    t1 = sorted(b for b, t in UPLIFT_TIER.items() if t == 'TIER1')
    # ⚠️ 2026-09-21 切 v8：TIER1 **成员换人** —— v7 {乐乐茶,瑞幸,茶百道} → v8 {奈雪,春莱,瑞幸}。
    #    ⚠️ 奈雪(n=10)/春莱(n=11) 是被**抬进来**的：CI 上界都恰好压在 clamp 天花板 1.2500。
    #       TIER1 免 clamp ⇒ 点估计 1.3632/1.5177 直接进引擎。这是"不加规则"的代价，
    #       已如实写进 brands.py 的 v8 注记；要修应改 TIER1 判据，属规则变更需单独裁决。
    check(t1 == ['奈雪', '春莱', '瑞幸'],
          'TIER1 只剩 3 个（v6 有 7 个：蜜雪/古茗/喜茶/霸王茶姬/茉莉奶白/'
          '个体杂牌/瑞幸）—— 剩下这几个才是 own_S 之外的显著偏差', str(t1))
    for b, up, n in (('瑞幸', 1.3271, 42), ('蜜雪冰城', 1.0000, 154),
                     ('古茗', 0.9970, 200), ('喜茶', 1.0399, 40),
                     ('茶百道', 0.9005, 69), ('个体/杂牌', 1.0000, 504)):
        check(abs(UPLIFT.get(b, 0) - up) < 1e-9 and _UPLIFT_N.get(b) == n,
              f'{b} = {up:.4f} / n={n}（v8 值）',
              f'实得 {UPLIFT.get(b)} / {_UPLIFT_N.get(b)}')
    # 消双算的**量化证据**：这两个值就是"品牌力被重复计入"的直接体现。
    #   蜜雪 v6 1.1903 → v7 1.0018 → v8 1.0000；
    #   个体/杂牌 v6 0.8370 → v7 1.0111 → v8 1.0000。
    check(abs(UPLIFT['蜜雪冰城'] - 1.0) < 0.01 and abs(UPLIFT['个体/杂牌'] - 1.0) < 0.02,
          '蜜雪 1.0000 / 个体杂牌 1.0000（v6 是 1.1903 / 0.8370）—— '
          '消双算后回到 1.0 附近，这正是 own_S 曾被重复计入的量级')

    p('')
    p('  ④ **双算的处置必须留在代码里**（说明"为什么这么改"，不能只写"改成什么"）')
    # v7 的核心论断：v6 的 uplift = DP_门店/商圈中位DP，而 DP 里的品牌差异**只**来自
    #   own_S（P 的分子是自己那项的 S、分母是周边竞品）→ uplift 在重复表达 own_S，
    #   而 own_S 已经通过 P 进过一次流水 ⇒ **双算**。
    #   处置是**换口径**（品牌盲残差），但必须把事实、实测数字与**残留局限**留在注释里，
    #   不能只留一句"仅供参考"（那样下一轮有人会把它当独立品牌证据去答辩）。
    braw = _read('src/engine/brands.py')
    check('双算' in braw, 'brands.py 注释里写明"双算"（v6 的 uplift 重复计入 own_S）',
          '找不到 ⇒ 局限被删了')
    check('品牌盲' in braw, 'brands.py 注释里写明"品牌盲"口径（自己 S 置 1.0 重算）')
    check('+0.6719' in braw and '+0.1531' in braw,
          '注释带**正交性实测**（Spearman(own_S, uplift) 从 +0.6719 降到 +0.1531）'
          '—— 只有结论没有数字，下一轮没人信')
    check('0.0243' in braw,
          '注释写明 clamp 低估的量级（瑞幸 v6 被截掉 0.0243），'
          '否则下一轮会以为 1.2500 是真实值')
    check('不能' in braw and '品牌溢价' in braw,
          '注释必须写明**残留局限**：残差只能读作"位置优势"，不能说成品牌溢价')

    p('')
    p('  ⑤ 卡片：已标定变多**不能**把无标定组挤没了')
    # v6 之前：已标定 9 个 + 无标定 6 个（room = 14−9）。
    # v6 之后：已标定 27 个 → 若沿用"总数 14 截断"，room = 14−27 = 0 ⇒
    #   无标定**一张都进不来**（甜啦啦/书亦烧仙草/茶颜悦色/7分甜… 共 14 个
    #   只能靠打字）——这是明确的功能回退，故改成"已标定全在 + 无标定保底"。
    from agent.agent_graph import build_brand_payload
    cards = build_brand_payload()['cards']
    cal = [c for c in cards if not c.get('self_created') and c['uplift'] is not None]
    oth = [c for c in cards if not c.get('self_created') and c['uplift'] is None]
    check(len(cal) == 27, '27 个已标定品牌**全在**卡片里（它们才是差异化价值）',
          f'实得 {len(cal)}（BRAND_S ∩ UPLIFT）')
    check(len(oth) >= 5, '无标定品牌仍有保底席位（不许被已标定挤成 0）',
          f'实得 {len(oth)}')
    check(any(c.get('self_created') for c in cards), '自创品牌逃生项仍在')
    names = [c['brand'] for c in cards]
    for b in ('古茗', '瑞幸', '一点点', '爷爷不泡茶'):
        check(b in names, f'诉求里的「{b}」在卡片上选得到')
    selfc = [c for c in cards if c.get('self_created')]
    if selfc:
        check(selfc[0]['n'] == 504 and selfc[0]['tier'] == 'TIER2',
              '自创品牌卡的 tier/n **随表更新**（v8 后是 TIER2/n=504 —— v7 是 '
              'TIER1/n=557；写死的旧值是 TIER2/n=7）',
              str({k: selfc[0][k] for k in ('tier', 'n', 'uplift')}))


async def main():
    p('verify_place_first.py —— 入口 B（地点优先）/ 候选扩量 / 租金面积三态 回归')
    p(f'  agent_graph.py {len(_read("src/agent/agent_graph.py"))} 字符 · '
      f'rental58.py {len(_read("src/agent/rental58.py"))} 字符 · '
      f'sidebar.js {len(_read("public/sidebar.js"))} 字符')
    p('  断言均跑在**去注释**文本上；网络相关部分只做解析逻辑真跑，不打外网')
    for name, fn in (('§1', s1), ('§2', s2), ('§3', s3), ('§4', s4), ('§5', s5),
                     ('§6', s6), ('§7', s7), ('§8', s8), ('§9', s9), ('§10', s10),
                     ('§11', s11), ('§12', s12), ('§13', s13), ('§14', s14),
                     ('§15', s15), ('§16', s16)):
        try:
            r = fn()
            if r is not None and hasattr(r, '__await__'):
                await r
        except Exception as e:
            # ⚠️ 一个脚本崩掉却**留下上一轮的旧报告**，比直接失败更危险：
            #    看报告的人会以为这套断言刚刚通过。所以逐节兜异常并记进报告。
            import traceback
            FAILS.append(f'{name} 抛异常 {type(e).__name__}: {e}')
            p(f'  FAIL  {name} 抛异常：{type(e).__name__}: {e}')
            p(traceback.format_exc()[-1200:])
    p('')
    p('=' * 74)
    if FAILS:
        p(f'FAILED = {len(FAILS)}：')
        for f in FAILS:
            p('   - ' + f)
    else:
        p('全部 PASS')
    p('=' * 74)
    (HERE / '_place_first_report.txt').write_text('\n'.join(L), encoding='utf-8')
    print('done, fails =', len(FAILS))
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
