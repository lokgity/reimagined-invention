# -*- coding: utf-8 -*-
"""需求 3 / 4 回归测试
- 需求4：自由对话咨询闸门（翻车输入必须转 chat；流程输入不能被误判）
- 需求4：手动「自由对话」开关短路
- 需求3：店铺优先入口识别 + 三件套收集 + 四品类反推测算 + 卡片负载
运行：C:/Python314/python.exe src/analysis/verify_flow_v2.py
"""
import sys
import asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'src'))

OUT = []


def p(s=''):
    OUT.append(str(s))


from agent.agent_graph import (  # noqa: E402
    classify_node, collect_shop_first_node, reverse_match_node,
    build_category_rec_payload, set_free_chat_mode,
    _is_consulting, _wants_shop_first, _wants_start_flow,
)

FAILS = []


def check(cond, label):
    if not cond:
        FAILS.append(label)
    return cond


def mk(user_msg, **over):
    st = {
        'messages': [{'role': 'user', 'content': user_msg}],
        'phase': 'intro', 'missing_info': [], 'candidates': [], 'list_shown': False,
        'hooks': {'steps': []},
    }
    st.update(over)
    return st


async def phase_of(msg, **over):
    r = await classify_node(mk(msg, **over))
    return r.get('phase')


async def main():
    # ================= 需求4：咨询闸门 =================
    p('=' * 70)
    p('需求4-1：以下输入必须判 chat（原先会被品类词/城市名拉进选址流程）')
    p('=' * 70)
    must_chat = [
        '奶茶店毛利率一般多少？',
        '便利店要办什么执照？',
        '杭州开店租金什么水平？',
        '开奶茶店需要注意什么风险？',
        '现在奶茶行业是不是已经饱和了',
        '甜品店装修一般多少钱',
        '早餐店要几个人才忙得过来',
    ]
    for t in must_chat:
        ph = await phase_of(t)
        check(ph == 'chat', f'应判 chat 却得到 {ph}：{t}')
        p(f"  [{'OK ' if ph == 'chat' else 'FAIL'}] {t:<34} -> {ph}")

    p()
    p('=' * 70)
    p('需求4-2：以下输入必须仍进选址流程（不能被闸门误伤）')
    p('=' * 70)
    must_flow = [
        ('我想开奶茶店', {'no_shop'}),
        # 2026-09-17（用户诉求①）：无品类的"帮我找铺子"从 no_shop 改为进 place_first
        # —— 判据不变，仍是"**不能被咨询闸门误伤成 chat**"；变的是进哪个选址入口。
        # 旧行为会反问"想开什么品类"，而那正是用户抱怨的"让我在前期自己选品类"。
        ('帮我找杭州滨江的铺子', {'place_first', 'no_shop'}),
        ('我想在宁波开个早餐店', {'no_shop'}),
        ('杭州滨江春晓路 60 号，月租 8000，40 平，想开便利店', {'have_shop'}),
        ('我有个铺子，想开奶茶店，月租 8000', {'have_shop'}),
        # 防回归：门牌号 + 明确"帮我找" -> 仍是搜索意图，不能被判成"已有具体商铺"
        ('帮我找滨江路 100 号附近的奶茶店', {'no_shop'}),
    ]
    for t, expect in must_flow:
        ph = await phase_of(t)
        check(ph in expect, f'应进流程({expect}) 却得到 {ph}：{t}')
        p(f"  [{'OK ' if ph in expect else 'FAIL'}] {t:<34} -> {ph}")

    p()
    p('=' * 70)
    p('需求4-3：手动「自由对话」开关必须短路一切（连"我想开奶茶店"也走 chat）')
    p('=' * 70)
    set_free_chat_mode(True)
    ph = await phase_of('我想开奶茶店，帮我找杭州滨江的铺子')
    check(ph == 'chat', f'自由对话开启时未短路，得到 {ph}')
    p(f"  [{'OK ' if ph == 'chat' else 'FAIL'}] 开启后「我想开奶茶店...」 -> {ph}")
    set_free_chat_mode(False)
    ph = await phase_of('我想开奶茶店')
    check(ph == 'no_shop', f'关闭自由对话后未恢复流程，得到 {ph}')
    p(f"  [{'OK ' if ph == 'no_shop' else 'FAIL'}] 关闭后「我想开奶茶店」 -> {ph}")

    # ================= 需求3：店铺优先 =================
    p()
    p('=' * 70)
    p('需求3-1：店铺优先入口识别')
    p('=' * 70)
    sf_cases = [
        ('我有个铺子但不知道开什么', 'shop_first'),
        ('店铺已经租下来了，做什么好', 'shop_first'),
        ('这里适合做什么生意', 'shop_first'),
        ('我有个铺子，月租 8000', 'shop_first'),      # 无品类 -> 店铺优先
    ]
    for t, expect in sf_cases:
        ph = await phase_of(t)
        check(ph == expect, f'应判 {expect} 却得到 {ph}：{t}')
        p(f"  [{'OK ' if ph == expect else 'FAIL'}] {t:<34} -> {ph}")

    p()
    p('  对照：有铺子 + 已想好品类 -> 仍走 have_shop（不该被反问品类）')
    ph = await phase_of('我有个铺子，想开奶茶店')
    check(ph == 'have_shop', f'有铺子+有品类应走 have_shop，得到 {ph}')
    p(f"  [{'OK ' if ph == 'have_shop' else 'FAIL'}] 我有个铺子，想开奶茶店        -> {ph}")

    p()
    p('=' * 70)
    p('需求3-2：三件套收集（缺什么问什么）')
    p('=' * 70)
    st = mk('我有个铺子但不知道开什么')
    r = await classify_node(st)
    st = {**st, **r, 'messages': st['messages']}
    r2 = await collect_shop_first_node(st)
    p(f'  第 1 轮（只说"有铺子"）-> phase={r2.get("phase")}, 缺={r2.get("missing_info")}')
    check(r2.get('phase') == 'shop_first', '缺信息时应留在 shop_first')
    check(set(r2.get('missing_info') or []) == {'地址', '月租金', '面积'},
          f'首轮应缺 地址/月租金/面积，得到 {r2.get("missing_info")}')
    msg = (r2.get('messages') or [])[-1].get('content', '')
    check('地址' in msg and '月租金' in msg and '面积' in msg, '追问文案必须点出三项')
    p('  追问文案：')
    for ln in msg.splitlines()[:8]:
        p('    | ' + ln)

    p()
    p('  第 2 轮（补上三件套）-> 应转入 reverse_match 并完成定位')
    st2 = dict(st)
    st2.update(r2)
    st2['messages'] = st2['messages'] + [
        {'role': 'user', 'content': '杭州滨江江陵路 88 号，月租 9000，面积 45 平米'}]
    r3 = await classify_node(st2)
    st3 = {**st2, **r3, 'messages': st2['messages']}
    r4 = await collect_shop_first_node(st3)
    p(f'  classify -> {r3.get("phase")}；collect -> {r4.get("phase")}')
    check(r3.get('phase') == 'shop_first',
          f'shop_first 阶段补信息后应保持 shop_first，得到 {r3.get("phase")}')
    p(f'  提取：地址={r4.get("address")!r} 月租={r4.get("rent")} 面积={r4.get("area")} '
      f'坐标={r4.get("pending_coord")}')
    check(r4.get('phase') == 'reverse_match',
          f'三件套齐备应转 reverse_match，得到 {r4.get("phase")}')
    check(r4.get('rent') == 9000, f'月租解析错误：{r4.get("rent")}')
    check(r4.get('area') == 45, f'面积解析错误：{r4.get("area")}')
    check(bool(r4.get('pending_coord')), '应完成 geocode 定位')

    p()
    p('=' * 70)
    p('需求3-3：四品类并联测算（排序依据 = 预估月净利）')
    p('=' * 70)
    coord = r4.get('pending_coord')
    if coord:
        st4 = {**st3, **r4, 'messages': st3['messages']}
        r5 = await reverse_match_node(st4)
        recs = r5.get('category_recs') or []
        check(bool(recs), 'reverse_match 未产出 category_recs')
        p(f'  产出 {len(recs)} 个品类：')
        p(f'  {"#":>2} {"品类":<6} {"月流水":>10} {"月净利":>10} {"回本(月)":>9} '
          f'{"净利率":>7} {"标签":<5}')
        for c in recs:
            sales = c.get('monthly_sales')
            net = c.get('monthly_net')
            pb = c.get('payback')
            nm = c.get('net_margin')
            p(f'  {c.get("i"):>2} {c.get("category"):<6} '
              f'{(f"{sales:,.0f}" if sales is not None else "n/a"):>10} '
              f'{(f"{net:,.0f}" if net is not None else "n/a"):>10} '
              f'{(f"{pb:.1f}" if isinstance(pb, (int, float)) else "n/a"):>9} '
              f'{(f"{nm:.1%}" if isinstance(nm, (int, float)) else "n/a"):>7} '
              f'{c.get("label", ""):<5}')
        # 排序校验：净利必须单调不增（有值的部分）
        vals = [c['monthly_net'] for c in recs if c.get('monthly_net') is not None]
        check(vals == sorted(vals, reverse=True), f'排序不是按净利降序：{vals}')
        p(f'  [{"OK " if vals == sorted(vals, reverse=True) else "FAIL"}] 净利降序排列正确')
        # 标签校验
        labeled = [c for c in recs if c.get('label')]
        check(all(c['label'] in ('首选', '可选', '谨慎') for c in labeled), '推荐标签取值非法')
        check(sum(1 for c in labeled if c['label'] == '首选') <= 1, '首选标签应至多一个')
        p(f"  [OK ] 标签：{'、'.join(c['category'] + '=' + c['label'] for c in labeled)}")

        p()
        p('  工作台卡片负载：')
        pl = build_category_rec_payload(recs)
        check(pl.get('kind') == 'category-rec', 'payload kind 错误')
        check(len(pl.get('cards') or []) == len(recs), 'payload 卡片数与结果数不符')
        check('跨品类不可比' in (pl.get('note') or ''), 'note 必须声明竞争分不可跨品类比较')
        p(f"    kind={pl['kind']}  title={pl['title']}  cards={len(pl['cards'])}")
        p(f"    note={pl['note'][:60]}…")
        p(f'    card[0]={pl["cards"][0]}')
    else:
        p('  [SKIP] 定位失败，跳过测算（可能是网络/地址问题）')

    p()
    p('=' * 70)
    p('需求3-4：反推后选方向 -> 走 have_shop（复用已收集信息，不重复追问）')
    p('=' * 70)
    for t in ['我选奶茶', '我选甜品', '我选便利店', '我选早餐']:
        ph = await phase_of(t, phase='reverse_match')
        check(ph == 'have_shop', f'reverse_match 后选品类应走 have_shop，得到 {ph}：{t}')
        p(f"  [{'OK ' if ph == 'have_shop' else 'FAIL'}] {t:<14} -> {ph}")
    ph = await phase_of('蜜雪冰城加盟费多少', phase='reverse_match')
    check(ph == 'chat', f'reverse_match 后问知识应判 chat，得到 {ph}')
    p(f"  [{'OK ' if ph == 'chat' else 'FAIL'}] 蜜雪冰城加盟费多少 -> {ph}")

    # ================= 汇总 =================
    p()
    p('=' * 70)
    if FAILS:
        p(f'❌ 失败 {len(FAILS)} 项：')
        for f in FAILS:
            p('   - ' + f)
    else:
        p('✅ 全部通过')
    p('=' * 70)

    (Path(__file__).resolve().parent / '_verify_flow_v2.txt').write_text(
        '\n'.join(OUT), encoding='utf-8')
    print('done, fails =', len(FAILS))


if __name__ == '__main__':
    asyncio.run(main())
    # ⚠️ 2026-09-15 补：原先失败也只打印、不设退出码 → 批量回归把它当"通过"，
    #    FAILS 非空却 rc=0，门禁形同虚设。必须让失败发出非零退出码。
    sys.exit(1 if FAILS else 0)
