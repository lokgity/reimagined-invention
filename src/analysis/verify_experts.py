# -*- coding: utf-8 -*-
"""verify_experts.py —— 专家层回归（P2）
==========================================================================
把 `src/experts/*.md` 里各专家的 `assertions` 尽量落成**机器可判**的断言，
并锁住专家层的三条结构性契约（全部本地、0 次 API，可离线复现）：

 1. **注册表纪律**：9 位齐全、blocked=0、工具只能取词汇表内名字、
    `tools ∩ forbids = ∅`、组内 order 唯一。写错一个字就该在这里挂，
    而不是等用户在对话里发现"这个专家说的话不对"。

 2. **专家必须"可验证地不同"**：`tools/forbids` 是专家的**可测差异**；
    "换了个人设"是测不出来的。所以断言关键差异项（谈判教练不调 score_site、
    门头审核员不调 solve_rent_limits、经营测算不调 score_site/elasticity_band…）。

 3. **公共铁律单源**：`_common.md` 是唯一一份定义，9 份 persona **不含任何副本**；
    `compose_system_prompt` 必须同时含铁律全文与 persona。附带一条**排版哨兵**：
    抓铁律条目编号重复/跳号（曾经把 11 写成第二个 10 —— 肉眼看不出，机器一眼看出）。

 4. **kb 分区一致性**：专家的 `kb_tags` 必须都在语料 tag 集合内；
    8 个 tag 都被至少一位专家用到（无孤儿 tag）；
    **分区检索必须是"全库算分、排序后过滤"** —— 断言分区结果是全库结果的
    子集、且同一条目分数不变（若改成按分区建索引，IDF 漂移会让这条挂）。

 5. **三个互斥起点不串味**（README §4.3）：已开店+有流水 → 经营诊断；
    有铺子+无品类+无流水 → 品类反推；两者不能互相抢。

 6. **已开店诊断接线**（专家系统 P1-2）：抽取器 / 意图 / classify 路由 / 图节点 /
    `diagnose_node` 端到端 / 规则兜底文本。
    §6b 是其**输入口径**（收入/租金/经营成本里的"万"不算前期投入；
    「日单量 × 每单金额」折月）；§6c 是**自由对话 > 已选专家**的优先级断言。

⚠️ 本套件**不**断言 LLM 的自由文本措辞（项目纪律：那类断言天然 flaky）。
真正针对 LLM 输出的两条断言放在末尾 §9，需显式开 `VERIFY_EXPERTS_LLM=1` 才跑，
**属网络信息性、不进离线门禁**。
§8 是"UI 需求接线哨兵"（源码级）：只断言接线存在，不保证 JS 逻辑正确。

用法：C:\\Python314\\python.exe src/analysis/verify_experts.py
输出：同目录 _verify_experts.txt
"""
import os
import re
import sys
import asyncio
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / '.pylibs'))

OUT = HERE / '_verify_experts.txt'
L = []
FAIL = []
INFO = []


def p(*a):
    s = ' '.join(str(x) for x in a)
    print(s)
    L.append(s)


def check(name, cond, detail=''):
    p(f'  {"PASS" if cond else "FAIL"}  {name}' + (f'  |  {detail}' if detail else ''))
    if not cond:
        FAIL.append(name)


def info(name, cond, detail=''):
    p(f'  ---- {name}' + (f'  |  {detail}' if detail else ''))
    if not cond:
        INFO.append(name)


from experts import registry as R
from agent import knowledge as KB
from agent.agent import (extract_monthly_revenue as EMR, extract_rent,
                         rule_based_diagnosis)
import agent.agent_graph as G

# =====================================================================
# §1 注册表纪律
# =====================================================================
p('=== §1 注册表纪律 ===')
experts = R.load_experts()
ids = set(experts)
check('9 位专家文件齐全（EXPECTED_IDS 对账）', ids == R.EXPECTED_IDS,
      f'{len(ids)} 位；缺={sorted(R.EXPECTED_IDS - ids)} 多={sorted(ids - R.EXPECTED_IDS)}')
ready = [e for e in experts.values() if e.status == 'ready']
check('blocked = 0（无专家被禁用）', len(ready) == len(experts),
      f'ready={len(ready)}/{len(experts)}')
groups = {}
for e in experts.values():
    groups.setdefault(e.group, []).append(e)
check('三组分布 = 开店前 6 / 开店后 1 / 阶段无关 2',
      {k: len(v) for k, v in groups.items()}
      == {'开店前决策链': 6, '开店后': 1, '阶段无关': 2},
      str({k: len(v) for k, v in groups.items()}))

bad_fields = []
for e in experts.values():
    for f in ('id', 'name', 'alias', 'blurb', 'group', 'order', 'one_liner',
              'start_sentence', 'tools', 'output_contract', 'fallback', 'status'):
        if getattr(e, f) in (None, '', []):
            bad_fields.append(f'{e.id}.{f}')
check('必填字段全部非空', not bad_fields, ','.join(bad_fields))

# --- alias / blurb：专家系统卡片页的两个展示字段（2026-09-16 升为必填） ---
# 为什么值得单独断言：这两个字段一旦为空，卡片页就退化成"只有岗位名的九宫格"，
# 也就是本轮需求想消灭的那种"写了等于没写"。缺了必须在启动时就炸，而不是等用户看到。
alias_all = [str(e.alias).strip() for e in experts.values()]
check('人名（alias）唯一', len(set(alias_all)) == len(alias_all),
      f'{len(set(alias_all))}/{len(alias_all)} 个不同')
bad_alias = [f'{e.id}:{e.alias!r}' for e in experts.values()
             if not (2 <= len(str(e.alias).strip()) <= 4)]
check('人名长度 2-4 字（好记，不是一句话）', not bad_alias, ','.join(bad_alias))
short_blurb = [f'{e.id}:{len(str(e.blurb))}字' for e in experts.values()
               if len(str(e.blurb)) < 40]
check('blurb ≥ 40 字（撑得起卡片页的"详细解释"）', not short_blurb, ','.join(short_blurb))
# 人名不能是岗位名的子串复用（"选址评估师"当人名 = 没起名字）
same_as_name = [e.id for e in experts.values()
                if str(e.alias).strip() in str(e.name)]
check('人名 ≠ 岗位名（真的起了名字）', not same_as_name, ','.join(same_as_name))
_cards = {c['id']: c for c in R.expert_choices()}
_bad_card = [i for i, c in _cards.items()
             if not c.get('alias') or not c.get('blurb') or 'order' not in c]
check('expert_choices() 带 alias/blurb/order（前端卡片的数据源）', not _bad_card,
      ','.join(_bad_card))
check('alias/blurb 已进 REQUIRED（缺了启动即失败）',
      {'alias', 'blurb'} <= set(R.REQUIRED), str(sorted(set(R.REQUIRED))))

bad_vocab, both = [], []
for e in experts.values():
    for t in list(e.tools) + list(e.forbids):
        if t not in R.VOCAB:
            bad_vocab.append(f'{e.id}:{t}')
    if set(e.tools) & set(e.forbids):
        both.append(f'{e.id}:{sorted(set(e.tools) & set(e.forbids))}')
check('tools/forbids ⊆ 工具词汇表（防拼写漂移）', not bad_vocab, ','.join(bad_vocab))
check('tools ∩ forbids = ∅（不自相矛盾）', not both, ';'.join(both))

dup_order = [g for g, v in groups.items()
             if len({e.order for e in v}) != len(v)]
check('组内 order 唯一', not dup_order, ','.join(dup_order))

# =====================================================================
# §2 专家必须"可验证地不同"
# =====================================================================
p('')
p('=== §2 专家可验证差异（tools/forbids）===')
toolsets = {frozenset(e.tools) for e in experts.values()}
check('tools 组合不全相同（专家非纯人设装饰）', len(toolsets) >= 4,
      f'{len(toolsets)} 种不同工具集')


def fb(x):
    return set(experts[x].forbids)


def tl(x):
    return set(experts[x].tools)


check('谈判教练不调 score_site / 不调经营诊断',
      {'score_site', 'diagnose_existing_store'} <= fb('rent_negotiator'),
      str(sorted(fb('rent_negotiator'))))
check('门头审核员不调 solve_rent_limits / 不调经营诊断',
      {'solve_rent_limits', 'diagnose_existing_store'} <= fb('storefront_auditor'),
      str(sorted(fb('storefront_auditor'))))
check('经营测算专家调 diagnose、且不调 score_site/elasticity_band/reverse_match',
      'diagnose_existing_store' in tl('store_diagnosis_advisor')
      and {'score_site', 'elasticity_band', 'reverse_match'}
      <= fb('store_diagnosis_advisor'),
      f'tools={sorted(tl("store_diagnosis_advisor"))}')
check('模型审计师不产任何评分/测算（forbids ⊇ score_site/elasticity_band/diagnose）',
      {'score_site', 'elasticity_band', 'diagnose_existing_store'}
      <= fb('model_auditor'))
# 模型审计师的 system prompt 必须注入实时数据块（live_facts），且**不含写死的旧样本量**。
# 2026-09-18 起因：审计师曾把锚点样本量写死为「83 家」，样本一扩就静默过期。
# 现在实时块主数字是扩样可用数（796），但 83/77 引擎生效真相必须并列保留 ——
# 断言的是「有实时块、不写死『样本量 83』」，而不是钉死某个数字（数字会随产物变）。
_ma_sp = R.compose_system_prompt('model_auditor')
check('模型审计师 system prompt 含实时数据块（本模型实时事实）',
      '本模型实时事实' in _ma_sp)
check('审计师实时块含扩样样本量（标定样本量）',
      '标定样本量' in _ma_sp and ('扩样' in _ma_sp))
check('审计师 prompt 不写死旧样本量「样本量 83」',
      '样本量 83' not in _ma_sp)
check('品类反推顾问 tools 含 reverse_match',
      'reverse_match' in tl('category_reverse'))
absent_users = [e.id for e in experts.values() if e.requires_absent]
check('requires_absent 唯一使用者 = 品类反推顾问（且值为 category）',
      absent_users == ['category_reverse']
      and experts['category_reverse'].requires_absent == ['category'],
      f'{absent_users} / {experts["category_reverse"].requires_absent}')

# =====================================================================
# §3 公共铁律单源
# =====================================================================
p('')
p('=== §3 公共铁律（单源 + 不复制 + 编号哨兵）===')
laws = R.common_laws()
check('铁律含"数字纪律"与"区间纪律"两节',
      '数字纪律' in laws and '区间纪律' in laws)
check('铁律含"一票否决优先级高于总分"',
      '一票否决' in laws and '优先级高于总分' in laws)
check('铁律字数 > 1500（内容未被清空）', len(laws) > 1500, f'{len(laws)} 字')

SENTINELS = ['严禁编造证据包之外的任何数字',
             '把它写成"你可以先出 X 元"等于让用户一开口就报出底线',
             '一票否决（veto）的优先级高于总分']
leaked = [f'{e.id}:{s[:12]}' for e in experts.values()
          for s in SENTINELS if s in e.persona]
check('9 份 persona 不含铁律副本（单源）', not leaked, ';'.join(leaked))

_raw = (ROOT / 'src' / 'experts' / '_common.md').read_text(encoding='utf-8')
_nums = [int(m.group(1)) for m in re.finditer(r'^(\d+)\.\s', _raw, re.M)]
check('铁律条目编号 1..13 连续且无重复（排版哨兵）',
      _nums == list(range(1, 14)), str(_nums))

compose_bad = []
for e in experts.values():
    sp = R.compose_system_prompt(e.id)
    if laws not in sp:
        compose_bad.append(f'{e.id}:缺铁律')
    if e.persona not in sp:
        compose_bad.append(f'{e.id}:缺persona')
    if len(sp) <= len(laws):
        compose_bad.append(f'{e.id}:未拼persona')
check('compose_system_prompt 逐专家 = 铁律全文 + persona 全文', not compose_bad,
      ','.join(compose_bad))

# =====================================================================
# §4 kb 分区一致性
# =====================================================================
p('')
p('=== §4 kb 分区（tag 合法 + 排序后过滤）===')
doc_tags = set()
for d in KB.KNOWLEDGE_BASE:
    doc_tags |= set(d.get('tags') or [])
exp_tags = set()
for e in experts.values():
    exp_tags |= set(e.kb_tags)
check('专家 kb_tags ⊆ 语料 tag 集合', exp_tags <= doc_tags,
      f'越界={sorted(exp_tags - doc_tags)}')
check('8 个语料 tag 均被至少一位专家使用（无孤儿 tag）', exp_tags == doc_tags,
      f'未用={sorted(doc_tags - exp_tags)}')
dead = [t for t in doc_tags
        if not any(t in (d.get('tags') or []) for d in KB.KNOWLEDGE_BASE)]
check('每个 tag 至少 1 条语料（无死分区）', not dead, ','.join(sorted(dead)))

_q = '蜜雪冰城加盟要多少钱'
_full = {d['title']: s for d, s in KB.retrieve(_q, top_k=500)}
_zone = {d['title']: s for d, s in KB.retrieve(_q, top_k=500, tags=['加盟政策'])}
check('分区结果 ⊆ 全库结果（排序后过滤，未另建索引）',
      set(_zone) <= set(_full), f'区外泄={sorted(set(_zone) - set(_full))}')
check('同一条目在 全库/分区 分数一致（IDF 未漂移）',
      all(abs(_zone[t] - _full[t]) < 1e-9 for t in _zone),
      f'{len(_zone)} 条比对')
check('分区检索确实收敛到该分区', all(
    '加盟政策' in (d.get('tags') or [])
    for d, _ in KB.retrieve(_q, top_k=500, tags=['加盟政策'])))

# =====================================================================
# §5 三个互斥起点不串味
# =====================================================================
p('')
p('=== §5 三个互斥起点（不互相抢）===')
check('已开店+流水 → diagnose', G._wants_diagnose('我店已经开了，月流水8万'))
check('有个店+营业额 → diagnose', G._wants_diagnose('我有个店，月营业额7万'))
check('找铺子 → 非 diagnose', not G._wants_diagnose('帮我找杭州滨江的奶茶店'))
check('纯咨询 → 非 diagnose', not G._wants_diagnose('奶茶店毛利率一般多少？'))
check('有铺子+无品类+无流水 → 非 diagnose（留给品类反推）',
      not G._wants_diagnose('我有个铺子，不知道做什么'))
check('有铺子+无品类+无流水 → shop_first 仍可用',
      G._wants_shop_first('我有个铺子，不知道做什么'))


async def _cls(text, prev='intro'):
    return await G.classify_node(
        {'messages': [{'role': 'user', 'content': text}], 'phase': prev})


_o = asyncio.run(_cls('我店已经开了，奶茶店月流水8万，月租1.2万'))
check('classify：已开店 → phase=diagnose', _o.get('phase') == 'diagnose',
      str(_o.get('phase')))
check('classify：带回月流水 80000', _o.get('monthly_revenue') == 80000,
      str(_o.get('monthly_revenue')))
check('classify：带回月租 12000', _o.get('rent') == 12000, str(_o.get('rent')))
_o2 = asyncio.run(_cls('月流水8万，月租1.2万', prev='diagnose'))
check('classify：diagnose 阶段继续报数 → 保持 diagnose',
      _o2.get('phase') == 'diagnose', str(_o2.get('phase')))

# =====================================================================
# §6 已开店诊断接线
# =====================================================================
p('')
p('=== §6 已开店诊断接线（抽取 → 路由 → 节点 → 兜底文本）===')
check('月流水8万 → 80000', EMR('我店月流水8万') == 80000, str(EMR('我店月流水8万')))
check('月营业额 7.5 万 → 75000', EMR('月营业额 7.5 万') == 75000)
check('流水3万5 → 35000（口语连读）', EMR('流水3万5') == 35000, str(EMR('流水3万5')))
check('日流水3000 → 90000（×30 折月）', EMR('日流水3000') == 90000, str(EMR('日流水3000')))
check('月租8000 不被误当流水', EMR('月租8000') is None)
check('无数字 → None（绝不猜）', EMR('我店已经开了，想看看') is None)
# 租金抽取器重构（共用 _apply_unit）后回归
check('月租1.2万 → 12000（重构无回归）', extract_rent('月租1.2万') == 12000)
check('装修预算20万 不当月租（原坑未复发）', extract_rent('装修预算20万') is None)

_g = G.build_agent_graph()
check('图中注册了 diagnose 节点', 'diagnose' in set(_g.get_graph().nodes.keys()))


async def _fake_llm(*a, **k):
    raise RuntimeError('__forced_fail__')


G.call_llm = _fake_llm          # 强制走规则兜底 → 断言确定、离线可复现


async def _diag(text, **extra):
    st = {'messages': [{'role': 'user', 'content': text}], 'phase': 'intro'}
    st.update(extra)
    return await G.diagnose_node(st)


_d0 = asyncio.run(_diag('我店已经开了，奶茶店'))
check('缺流水 → 追问且 phase=diagnose',
      _d0.get('phase') == 'diagnose' and '月流水' in _d0['messages'][-1]['content'])
check('缺流水 → 不产 store_diagnosis（不返回空壳）',
      _d0.get('store_diagnosis') is None)

_d1 = asyncio.run(_diag('我店已经开了，奶茶店，月流水8万，月租1.2万，30平'))
_sd = _d1.get('store_diagnosis') or {}
check('齐备 → 产出 store_diagnosis 且 phase=chat',
      bool(_sd) and _d1.get('phase') == 'chat')
check('诊断含三种毛利口径（毛利率/扣渠道后/净利率）',
      None not in (_sd.get('毛利率'), _sd.get('扣渠道后毛利率'), _sd.get('净利率')),
      f"{_sd.get('毛利率')}/{_sd.get('扣渠道后毛利率')}/{_sd.get('净利率')}")
check('诊断含安全边际率', _sd.get('安全边际率') is not None,
      str(_sd.get('安全边际率')))
check('诊断成本拆解用规范键「月成本合计」',
      '月成本合计' in (_sd.get('成本拆解') or {}))
check('外卖抽成占流水比 ≈ 7.7%（中性档，非 22% 佣金率）',
      abs((_sd.get('外卖抽成占流水比') or 0) - 0.077) < 0.02,
      str(_sd.get('外卖抽成占流水比')))

_d2 = asyncio.run(_diag('我店已经开了，奶茶店，月流水0，月租1.2万'))
check('月流水 0 → 不产空壳、提示核对',
      _d2.get('store_diagnosis') is None
      and '核对' in _d2['messages'][-1]['content'])

_d3 = asyncio.run(_diag('我店已经开了，蜜雪冰城，月流水8万，月租1.2万'))
_sd3 = _d3.get('store_diagnosis') or {}
check('仅报品牌也能推品类（蜜雪冰城 → 奶茶，查表非编造）', bool(_sd3),
      f'品类={_sd3.get("品类")}')
check('有公开数据的品牌 → 给对标且带披露期',
      bool((_sd3.get('品牌对标') or {}).get('期间')),
      str((_sd3.get('品牌对标') or {}).get('期间')))

_txt = rule_based_diagnosis(_sd)
check('规则兜底：含"安全边际"与"成本拆解"',
      '安全边际' in _txt and '成本拆解' in _txt)
check('规则兜底：三种毛利口径同时出现',
      all(k in _txt for k in ('产品口径', '扣渠道后', '净利率')))
check('规则兜底：不含"预估月流水"（不估流水）', '预估月流水' not in _txt)
check('规则兜底：附局限声明（⚠️）', '⚠️' in _txt)

# ---------------------------------------------------------------------
# §6b 诊断的**输入口径**（2026-09-17）
#   ① 收入 / 租金 / 经营成本里的"万"**不算前期投入**
#   ② 「日单量 × 每单金额」折月（persona 一直承诺、节点此前从没接线）
# 为什么必须钉住：这两处错了都**不报错**，只是净利与回本悄悄算歪 ——
# 属于"错得很自信"的那类，只能靠断言发现。
# ---------------------------------------------------------------------
p('')
p('--- §6b 诊断输入口径：前期投入 / 每单金额 / 日单量 ---')
for _t, _want, _why in [
        ('月流水 8.6 万', None, '流水不是投入（修复前读到 86000）'),
        ('月租 1.2 万', None, '租金不是投入（修复前读到 12000）'),
        ('月成本 6.2 万', None, '经营成本不是投入（修复前读到 62000）'),
        ('前期投入 24 万', 240000, '写明投入必须照读'),
        ('预算 12 万', 120000, '预算口径必须照读（掩码曾把它一起挖掉）'),
        ('月流水 8.6 万，月租 1.2 万，前期投入 24 万', 240000, '三数并存时只认投入'),
]:
    _got = G._parse_investment(_t, strict=True)
    check(f'strict 投入口径：{_t} → {_got!r}', _got == _want, _why)
check('strict 下没有口径词的"12 万"→ None（认错会静默算歪，缺了会被追问）',
      G._parse_investment('12 万', strict=True) is None)
check('collect_invest 环节裸答"12 万"→ 120000（宽松路径不受影响）',
      G._parse_investment('12 万', strict=False) == 120000)
check('即便宽松路径，"月流水 8.6 万"也不算投入（掩码兜住）',
      G._parse_investment('月流水 8.6 万', strict=False) is None)

check('每单金额 15 元 → 15', G._parse_price('每单金额 15 元') == 15)
check('客单价 12.5 元 → 12.5（客单价口径 = 每单金额）',
      G._parse_price('客单价 12.5 元') == 12.5)
check('单杯价 9 元 → None（单杯价 ≠ 每单金额，不许混用）',
      G._parse_price('单杯价 9 元') is None)
check('日单量 190 单 → 190', G._parse_daily_orders('日单量 190 单') == 190)
check('"日流水 3000" → 日单量 None（那是金额不是单量）',
      G._parse_daily_orders('日流水 3000') is None)

_d4 = asyncio.run(_diag('我店已经开了，奶茶店，月租 12000 元，日单量 190 单，'
                        '每单金额 15 元，面积 30 平米'))
_sd4 = _d4.get('store_diagnosis') or {}
check('只报「日单量 × 每单金额」→ 折月 85500 并直接出诊断',
      (_sd4.get('输入') or {}).get('实际月流水') == 190 * 15 * 30,
      f"月流水={(_sd4.get('输入') or {}).get('实际月流水')!r}")
check('折月后不再追问月流水', not _d4.get('missing_info'),
      str(_d4.get('missing_info')))

from engine.store_diagnosis import diagnose_existing_store as _DES  # noqa: E402
_ok_ref = _DES('奶茶', 86000, 12000, area_m2=30, city='宁波', investment=None)
_bad_ref = _DES('奶茶', 86000, 12000, area_m2=30, city='宁波', investment=86000)
_d5 = asyncio.run(_diag('我店已经开了，奶茶店，月流水 8.6 万，月租 12000 元，'
                        '面积 30 平米'))
_sd5 = _d5.get('store_diagnosis') or {}
check('只报流水时，前期投入按引擎默认（与显式 investment=None 逐位一致）',
      abs((_sd5.get('成本拆解') or {}).get('月摊销', -1)
          - _ok_ref['成本拆解']['月摊销']) < 1,
      f"月摊销={(_sd5.get('成本拆解') or {}).get('月摊销')}；"
      f"若被流水污染会是 {_bad_ref['成本拆解']['月摊销']}")

# ---------------------------------------------------------------------
# §6c 自由对话 > 已选专家（2026-09-17 用户诉求）
# "打开自由对话后，别再受我选了哪位专家影响 —— 我可以问天气、问电视剧"
# 断言方式是**捕获真实的 system prompt / tools / kb_tags**，不是读源码猜。
# ---------------------------------------------------------------------
p('')
p('--- §6c 自由对话优先级：开启后不再受已选专家影响 ---')
_CAP = {}
_orig_call = G.call_llm
_orig_tools = G.call_llm_with_tools
_real_kb = G.kb_context


async def _cap_llm(system, user, **k):
    _CAP['system'] = system
    _CAP['tool_mode'] = False
    return '（打桩回答）'


async def _cap_llm_tools(system, user, tools=None, **k):
    _CAP['system'] = system
    _CAP['tool_mode'] = True
    _CAP['tools'] = list(tools or [])
    return '（打桩回答）', []


def _spy_kb(q, top_k=3, tags=None):
    _CAP['kb_tags'] = tags
    return _real_kb(q, top_k=top_k, tags=tags)


G.call_llm = _cap_llm
G.call_llm_with_tools = _cap_llm_tools
G.kb_context = _spy_kb


def _free_chat_run(free, expert='store_diagnosis_advisor'):
    st = {'messages': [{'role': 'user', 'content': '今天杭州天气怎么样？'}]}
    if expert:
        st['expert'] = expert
    G.set_free_chat_mode(free)
    _CAP.clear()
    try:
        asyncio.run(G.free_chat_node(st))
    finally:
        G.set_free_chat_mode(False)
    return dict(_CAP)


_off = _free_chat_run(False)
check('对照：未开自由对话时专家照旧生效（人设 + 铁律 + 工具 + 知识分区）',
      '经营测算专家' in _off.get('system', '')
      and '以下是所有专家都必须遵守的铁律' in _off.get('system', '')
      and _off.get('tool_mode') is True
      and _off.get('kb_tags') == ['营销与运营', '成本与政策'],
      f"tools={len(_off.get('tools') or [])} tags={_off.get('kb_tags')!r}")

_on = _free_chat_run(True)
check('开启自由对话 → 换通用助手人设（专家 persona 不进 prompt）',
      '自由对话' in _on.get('system', '')
      and '经营测算专家' not in _on.get('system', ''))
check('开启自由对话 → 专家那套公共铁律也不再进 prompt',
      '以下是所有专家都必须遵守的铁律' not in _on.get('system', ''))
check('开启自由对话 → 不开专家工具白名单（工具调用让位）',
      _on.get('tool_mode') is False)
check('开启自由对话 → 知识库不再限定专家分区（回到全库检索）',
      _on.get('kb_tags') is None, repr(_on.get('kb_tags')))
check('通用助手人设点名天气/影视剧要正常答，且实时信息**先声明**无联网（不许编）',
      '天气' in _on.get('system', '') and '必须先说明' in _on.get('system', ''))
check('未选专家 + 自由对话 也走通用助手人设（两条入口统一）',
      '自由对话' in _free_chat_run(True, expert='').get('system', ''))

G.call_llm = _orig_call
G.call_llm_with_tools = _orig_tools
G.kb_context = _real_kb

# =====================================================================
# §8 四个 UI 需求的接线哨兵（源码级；只断言"接线在"，不断言措辞）
# =====================================================================
# 本轮（2026-09-16）四个 UI 需求全部落在 app_chainlit.py + public/sidebar.js，
# 它们不进 Python 运行时、没法用 import 断言。退而求其次：断言"关键接线存在"。
# ⚠️ 这类断言只防"被误删/被重构掉"，不保证 JS 逻辑正确 —— 后者只能靠手测。
p('')
p('=== §8 UI 需求接线哨兵（问题 1-4）===')
APP = (ROOT / 'src' / 'ui' / 'app_chainlit.py').read_text(encoding='utf-8')
JS = (ROOT / 'public' / 'sidebar.js').read_text(encoding='utf-8')

# 问题 1：按按钮时对话框不能有任何输出
check('后端：自由对话开关不再回文字消息（问题1）',
      '已开启「自由对话」' not in APP and '已关闭自由对话' not in APP)
check('后端：专家静默通道存在（##专家: 不回消息）（问题1）',
      '_silent = text.startswith' in APP and 'silent=silent' in APP
      or 'silent=_silent' in APP)
check('后端：##专家:xxx## 尾巴已削（潜伏的 id 匹配 bug 不会复发）',
      "rstrip('#').strip()" in APP)
check('前端：静默白名单 5 处都含「自由对话|专家」（问题1 根因）',
      JS.count('自由对话|专家') >= 5, f'出现 {JS.count("自由对话|专家")} 次')
check('前端：MutationObserver 也探测 自由对话/专家',
      "indexOf('##自由对话:')" in JS and "indexOf('##专家:')" in JS)
check('前端：rAF 加固（把极端可见窗口压到 1 帧）',
      'rafHide' in JS and 'requestAnimationFrame' in JS)
check('前端：有通用浮层提示（不写进对话历史）',
      'function showToast' in JS and 'xb-toast' in JS)

# 问题 2：首屏导航词精简
# 只对「欢迎语正文」断言，不对整个文件 —— 源码注释里会**故意**提到被删掉的旧文案
# （"曾经铺了 6 条 bullet + 一整块想找谁聊"），naive 的全文 not in 会被自己的注释绊倒。
_m = re.search(r'welcome = """(.*?)"""', APP, re.S)
WELCOME = _m.group(1) if _m else ''
check('后端：欢迎语可提取到', bool(WELCOME), f'{len(WELCOME)} 字')
check('后端：首屏不再有「想找谁聊？」整块（问题2）', '想找谁聊' not in WELCOME)
check('后端：首屏不再逐条罗列功能点（问题2）', '我能帮你做什么' not in WELCOME)
check('后端：首屏不再复述门头照 / 砍价单点功能（问题2 去重）',
      '传一张门头照' not in WELCOME and '想砍价' not in WELCOME)
check('后端：欢迎语 < 600 字（真的是"三句总览"，不是又长回来）',
      len(WELCOME) < 600, f'{len(WELCOME)} 字')
check('后端：首屏只剩欢迎语一条消息（send_expert_picker 已移除）',
      'send_expert_picker' not in APP)
check('后端：欢迎语把找人的入口指向输入框上方 + 左栏（问题3/4）',
      '输入框上方' in WELCOME and '专家系统' in WELCOME)

# 问题 3：输入框上方的专家条（二级展开 + 恒跟随）
check('前端：专家条 DOM/CSS 存在（问题3）',
      "bar.id = 'zl-xbar'" in JS and '#zl-xbar .xb-panel' in JS)
check('前端：专家条恒跟随输入框（layout() 内重算 + 锚 bottom）',
      'function layoutBar' in JS and 'layoutBar();' in JS
      and 'window.innerHeight - r.top' in JS)
check('前端：二级面板 9 行由数据渲染（不写死）',
      'EXPERTS.forEach' in JS and 'data-xid' in JS)

# 问题 4：左侧「专家系统」子页（3×3）
check('前端：左栏新增「专家系统」入口（问题4）', 'data-xpage="experts"' in JS
      or "data-xpage='experts'" in JS or 'data-xpage' in JS)
check('前端：严格三列网格（grid-template-columns:repeat(3,...)）',
      'repeat(3,minmax(0,1fr))' in JS)
check('前端：卡片页含 人名 + 详细解释 + 示例（问题4）',
      'zl-ex-blurb' in JS and 'zl-ex-name' in JS and 'zl-ex-no' in JS)
check('前端：点卡片即切专家（共用 switchExpert）',
      'data-xpick' in JS and 'function switchExpert' in JS)

# 单一真源：前端不许写死专家清单
check('前端未写死专家 id（加专家 = 加 md 文件、不改代码）',
      'site_advisor' not in JS and 'rent_negotiator' not in JS)

# ---------------------------------------------------------------------
# §8a-2 2026-09-18 欧文两条诉求
#   ① 快速演示加**反面教材**（真实低分案例）
#   ② 专家卡与快捷条里，**「定位」必须压过「拟人名」**（改前是反的）
# ⚠️ 断言一律写成"代码形状"（含 拼接/属性 的整段），否则旁边的中文注释
#    会把断言**自指**满足掉（本项目的老坑）。
# ---------------------------------------------------------------------
p('')
p('§8a-2 专家展示：定位压过拟人名（2026-09-18）')
check('前端：专家子页卡片 = 定位在前、拟人名在后（诉求②）',
      '\'<span class="zl-ex-name">\' + esc(e.name)' in JS
      and 'esc(e.alias || \'\') + \'</span></span>\'' in JS)
check('前端：快捷条每行同样是定位在前、拟人名在后（诉求②）',
      '<b class="xb-role">\' + esc(e.name)' in JS
      and '<span class="xb-alias">\' + esc(e.alias' in JS)
check('前端：顶部「当前专家」按 定位·拟人名 展示，且 exLabel 是唯一真源',
      "e.name + ' · ' + e.alias" in JS and 'function exCurHTML' in JS)
# ⚠️ 字体缩放层写在基础规则**之后**、且只覆盖 font-size —— 它才是"最终生效值"。
#    2026-09-18 第一版只改了基础规则（20/13），实机量出来仍是 19.5/14（被这里静默盖掉）。
check('前端：缩放层字号与基础规则一致（定位 20 / 人名 13，防"只改一处被盖掉"）',
      'calc(20px * var(--zl-fs))' in JS and 'calc(13px * var(--zl-fs))' in JS)
check('后端：切换回执与 `/expert` 列表都改成 定位 · 拟人名（与前端同口径）',
      '已切换到 **{ex.name} · {ex.alias}**' in APP
      and '**{e.name} · {e.alias}**' in APP)
check('后端：/expert 解析器两种顺序都认（旧写法「人名·定位」仍能切过去）',
      "f'{e.name}·{e.alias}'" in APP and "f'{e.alias}·{e.name}'" in APP)

p('')
p('§8a-3 快速演示：反面教材（2026-09-18 诉求①）')
check('前端：演示组有小标题 + 2 个反面按钮（且用独立样式与正面区分）',
      'class="zl-demo-sub"' in JS and 'class="zl-btn bad"' in JS
      and 'data-cmd="demo_bad_rent"' in JS and 'data-cmd="demo_bad_place"' in JS)
check('前端：两个反面按钮都带**实测结论**的说明（title 里写清为什么低分）',
      JS.count('真实低分案例（选蜜雪冰城）') == 2)
check('前端：反面演示问句带品牌 + 真实点位（不写品牌会先进"选品牌"，演示就不确定）',
      "demo_bad_rent: '有，看中了杭州湖滨银泰in77" in JS
      and "demo_bad_place: '有，看中了杭州千岛湖银泰城" in JS
      and '加盟蜜雪冰城' in JS)

# ---------------------------------------------------------------------
# §8b 第二批需求接线哨兵（2026-09-16：自托管圆体 / 三控件同行 / 附件抽取）
# ---------------------------------------------------------------------
p('')
p('--- §8b 第二批：字体 · 同行控件 · 附件抽取 ---')
CSS = (ROOT / 'public' / 'app.css').read_text(encoding='utf-8')
GRAPH = (ROOT / 'src' / 'agent' / 'agent_graph.py').read_text(encoding='utf-8')
FONTS = ROOT / 'public' / 'fonts'

# ① 自托管中文圆体（离线可用，不依赖 CDN）
check('字体：子集 woff2 已落盘（离线自托管）',
      (FONTS / 'zl-rounded-sc.woff2').exists(),
      f'{(FONTS / "zl-rounded-sc.woff2").stat().st_size / 1048576:.2f} MB'
      if (FONTS / 'zl-rounded-sc.woff2').exists() else '缺失')
check('字体：@font-face 声明在 app.css（不是 CDN 链接）',
      '@font-face' in CSS and 'ZL Rounded SC' in CSS and 'http' not in
      CSS[CSS.find('@font-face'):CSS.find('@font-face') + 400])
check('字体：FONT 栈首项是自托管圆体',
      'var FONT = \'"ZL Rounded SC"' in JS)
check('字体：OFL 许可文本随字体分发（改名合规的前提）',
      (FONTS / 'LICENSE-WenYuanFonts.md').exists())
check('字体：家族名已避开保留字体名（子集属修改版，不得沿用原名）',
      'ZL Rounded SC' in CSS and 'WenYuanRoundedSCVF' not in CSS)

# ② 三控件并排同一行（选择专家 | 自由对话 | 模型）
check('同行：专家条内含 .xb-tools 行与两个右侧插槽',
      'xb-tools' in JS and "id=\"xb-slot-fc\"" in JS and "id=\"xb-slot-md\"" in JS)
check('同行：模型/自由对话改为挂进插槽（不再只寄生在回形针旁）',
      "homeSlot('xb-slot-md')" in JS and "homeSlot('xb-slot-fc')" in JS)
check('同行：专家条建好后会把控件收回插槽（顺序无关、自愈）',
      JS.count('ensureModelSelect();') >= 2)
check('同行：面板限高按**整行**高度算（否则 9 行会被顶出视口）',
      "bar.querySelector('.xb-tools')" in JS and 'rowH' in JS)

# ③ 子页面字号进缩放层（设置里的「字体大小」以前对子页面无效）
check('字号：子页面已纳入 --zl-fs 缩放层',
      '#zl-page-ov .zl-ex-blurb{font-size:calc(' in JS
      and '#zl-page-ov .zl-kb-card{font-size:calc(' in JS)

# ④ 非图片附件文本抽取（过去 PDF 被静默丢弃）
check('附件：存在 PDF 抽取函数（PyMuPDF）', 'def _extract_pdf' in APP and 'fitz.open' in APP)
check('附件：存在非图片附件的分派（cl.Pdf / text / docx）',
      'def _extract_attachment' in APP and 'cl.Pdf' in APP and 'def process_attachment' in APP)
check('附件：on_message 不再只挑图片（非图片走 docs 分支）',
      'docs = [el for el in els if el not in images]' in APP)
check('附件：抽取为空（扫描件）时明说不读，不假装成功',
      '没有文本层' in APP and '不会假装已经读到了内容' in APP)
check('附件：多图/多文件不再静默丢弃（有提示）',
      '本次**只分析第 1 张**' in APP or '本次只分析第 1 张' in APP)
check('附件：正文会注入自由对话上下文（agent_graph 侧）',
      "state.get('attachments')" in GRAPH and '附件正文' in GRAPH)
check('附件：注入点在 system_msg 三分支之后（改一处即覆盖全部路径）',
      # 用 rfind（最后一个出现）：diagnose 节点也读 attachments（解析源，见 1662 行附近），
      # find 会命中它、早于 elif context 而误报。注入点特指 interpret 三分支之后那处。
      GRAPH.rfind("state.get('attachments')") > GRAPH.rfind('elif context:'))
check('附件：自由对话模式下传图不并入评分、不改会话品牌',
      'if not chat_mode and vlm.get(\'识别品牌\')' in APP
      and 'if result and not chat_mode' in APP)
check('附件：持久化时剥掉正文（防 conversations.json 膨胀）',
      'def _attach_brief' in APP and '_attach_brief(slim' in APP)
# ⚠️ 下面两条守的是"PDF 一读就散成一片碎行"这个具体缺陷（2026-09-18 修）：
#   ① 抽取层：`get_text('text')` 会把**同一视觉行、横向间隔较大**的几段拆成多行
#      （《店铺经营月报》实测：`月流水`/`120000`/`元` 的 y 坐标完全相同却各占一行），
#      必须改用 `_pdf_page_text` 按 word 坐标重建视觉行。
#   ② 展示层：Chainlit 2.11.1 的 markdown 把 `p` 渲染成 `whitespace-pre-wrap`，
#      于是**每个换行都是真换行**，预览若直接铺原文就是"几个字一行 + 满屏空白"，
#      必须走 `_compact_preview`。
check('附件：PDF 正文按坐标重建视觉行（不再被 get_text 拆成一行一个词）',
      'def _pdf_page_text' in APP and '_pdf_page_text(doc.load_page' in APP)
check('附件：预览压成紧凑块（Chainlit 的 p 是 pre-wrap，换行即真换行）',
      'def _compact_preview' in APP and '_compact_preview(text, ATTACH_PREVIEW)' in APP)

# =====================================================================
# §8c 第三批：专家真接 function calling（2026-09-16，§6）
# =====================================================================
p('')
p('--- §8c 真 function calling：白名单即执行边界 · 证据包 · 人设归位 ---')
from experts import toolbox as TB        # noqa: E402
from agent.agent_graph import build_evidence_pack as _bep   # noqa: E402

# ① 工具目录与词汇表一致（VOCAB 是超集；TOOLS 里的名字必须都登记过）
check('工具箱里的工具都在注册表 VOCAB 内（不会出现"野工具"）',
      set(TB.TOOLS) <= set(R.VOCAB),
      f'未登记：{sorted(set(TB.TOOLS) - set(R.VOCAB))}')

# ② 白名单 = tools − forbids，且**逐位专家不同**（这才是可测差异）
allow_rent = TB.allowed_tools('rent_negotiator')
allow_fra = TB.allowed_tools('franchise_advisor')
allow_pol = TB.allowed_tools('startup_policy_advisor')
check('白名单确实按专家分化（谈判教练 ≠ 加盟顾问）',
      allow_rent != allow_fra and bool(allow_rent) and bool(allow_fra),
      f'rent={len(allow_rent)} 个 / franchise={len(allow_fra)} 个')
check('forbids 优先于 tools（谈判教练不得 score_site / analyze_storefront）',
      'score_site' not in allow_rent and 'analyze_storefront' not in allow_rent)
check('政策顾问的工具被收窄到只剩知识库', allow_pol == {'kb_retrieve'},
      str(sorted(allow_pol)))

# ③ **调用被拒**：越界调用必须返回 denied=True，并把原因回灌给模型（文档曾声称的
#    "调用被拒"在改造前根本不存在 —— call_llm 连 tools 参数都没有）
_r1 = TB.run_tool('rent_negotiator', 'diagnose_existing_store', {})
check('越界调用被拒（谈判教练调经营诊断 → denied）',
      _r1.get('denied') is True and '调用被拒' in (_r1.get('error') or ''),
      (_r1.get('error') or '')[:56])
_r2 = TB.run_tool('rent_negotiator', 'score_site', '{}')
check('forbids 命中时文案点明"该能力被明确禁止"',
      _r2.get('denied') is True and '明确禁止' in (_r2.get('error') or ''),
      (_r2.get('error') or '')[:56])
_r3 = TB.run_tool('startup_policy_advisor', 'get_franchise_info', '{"brand":"蜜雪冰城"}')
check('政策顾问越界查加盟信息 → denied', _r3.get('denied') is True)
_r4 = TB.run_tool('site_advisor', '根本没有的工具', '{}')
check('未登记工具也拒绝（不静默返回空）', _r4.get('denied') is True)

# ④ 白名单内的**可执行**工具真的能跑（不是空壳），取不到就说取不到
_k = TB.run_tool('model_auditor', 'kb_retrieve', '{"query":"口径区间 弹性 未标定"}')
check('白名单内工具可真实执行（kb_retrieve 返回正文）',
      bool(_k.get('ok')) and bool((_k.get('result') or {}).get('知识库结果')))
_b = TB.run_tool('franchise_advisor', 'brand_order_value', '{"brand":"蜜雪冰城"}')
check('品牌工具可执行并返回每单金额',
      bool(_b.get('ok')) and bool((_b.get('result') or {}).get('每单金额')),
      str((_b.get('result') or {}).get('每单金额')))
_m = TB.run_tool('franchise_advisor', 'brand_store_metrics', '{"brand":"奈雪的茶"}')
check('别名归一后能取到"奈雪的茶"公开行（旧实现该行永远取不到）',
      bool(_m.get('ok')) and (_m.get('result') or {}).get('品牌') == '奈雪的茶',
      str((_m.get('result') or {}).get('品牌')))
_co = TB.run_tool('site_advisor', 'rule_based_interpret', '{}')
check('"需要上下文"的工具被调用时如实说明不供主动调用（不编数字）',
      _co.get('ok') is False and '不供模型主动调用' in (_co.get('error') or ''),
      (_co.get('error') or '')[:56])
# kb 分区：同一次查询，两位专家命中不同分区 → 结果不同（专家差异的来源之一）
_ka = TB.run_tool('startup_policy_advisor', 'kb_retrieve', '{"query":"补贴 政策"}')
_kb = TB.run_tool('competitor_analyst', 'kb_retrieve', '{"query":"补贴 政策"}')
check('同一查询在两位专家下命中不同分区（kb_tags 生效）',
      (_ka.get('result') or {}).get('知识库结果')
      != (_kb.get('result') or {}).get('知识库结果'))

# ⑤ 暴露给模型的 schema 只含"白名单 ∩ 已实现"
_sch = TB.tool_schemas('franchise_advisor')
_names = {s['function']['name'] for s in _sch}
check('tool_schemas 只暴露白名单内的已实现工具',
      bool(_names) and _names <= allow_fra and _names <= set(TB.TOOLS),
      str(sorted(_names))[:110])
check('tool_schemas 是合法 OpenAI 结构（type=function + name/parameters object）',
      all(s.get('type') == 'function' and s['function'].get('name')
          and s['function'].get('parameters', {}).get('type') == 'object'
          for s in _sch))
check('"需要会话上下文"的工具不出现在 schema（不给模型假期望）',
      not ({'score_site', 'negotiation_brief', 'diagnose_existing_store'} & _names))

# ⑥ LLM 层真的有 tools 通道（旧实现只有 system+user 两条消息）
LLM = (ROOT / 'src' / 'agent' / 'llm.py').read_text(encoding='utf-8')
check('llm.py 有 message 级调用（保留 tool_calls；旧 _call_llm 会把它丢掉）',
      'def _post_messages' in LLM and "return msg.get('content') or ''" in LLM)
check('llm.py 有 call_llm_with_tools（tools 参数 + 多轮回合 + tool_choice）',
      'async def call_llm_with_tools' in LLM and "payload['tools'] = tools" in LLM
      and 'tool_choice' in LLM)
check('工具调用有轮数上限（防模型无限调工具把界面拖死）', 'max_rounds' in LLM)
check('provider 不支持 tools 时自动降级为普通调用（严格增量，不新增故障点）',
      '已降级为普通对话' in LLM and 'use_tools=False' in LLM)

# ⑦ 接线哨兵：free_chat 用证据包 + 工具；未选专家逐字不变
check('free_chat 注入**结构化证据包**（不再只有一行 context 摘要）',
      'build_evidence_pack(state)' in GRAPH
      and '【当前会话已完成的结构化证据包（真实数据）】' in GRAPH)
check('free_chat 只在"显式选了专家"时开工具（默认路径不变）',
      'expert_toolbox.tool_schemas(_sel) if _sel else []' in GRAPH)
check('free_chat 把真实工具调用写进「执行过程」（用户可核查调了什么/被拒了什么）',
      '工具调用（' in GRAPH and '被拒：' in GRAPH)
check('解释节点人设归位：固定 site_advisor（不再被 _expert_id 带偏）',
      '_INTERP_EXPERT = DEFAULT_EXPERT' in GRAPH)
_ib = GRAPH.find('async def interpret_node')
_ie = GRAPH.find('async def free_chat_node')
check('interpret 段内不再用 _expert_id(state)（修"用错了人"）',
      _ib > 0 and _ie > _ib and '_expert_id(state)' not in GRAPH[_ib:_ie])
check('§4：interpret 的 prompt 已裁剪（段内不再整份 json.dumps(result)）',
      'json.dumps(_view, ensure_ascii=False)' in GRAPH[_ib:_ie]
      and 'json.dumps(result, ensure_ascii=False)' not in GRAPH[_ib:_ie])

# ⑧ 三位"形同虚设"的专家现在真的走 LLM（改造前他们的 persona 从未进过 prompt）
check('品类反推师接 LLM（人设首次进入 prompt）',
      "_expert_commentary('category_reverse'" in GRAPH)
check('加盟顾问接 LLM（不再借用竞品分析师的人设）',
      "_expert_commentary('franchise_advisor'" in GRAPH)
check('门头审核员接 LLM（VLM 结果后加一层 persona 解读）',
      "_expert_commentary('storefront_auditor'" in APP)
_cb0 = GRAPH.find('async def _expert_commentary')
check('附加解读失败返回空串（调用方保持引擎模板文案，严格增量）',
      _cb0 > 0 and "return ''" in GRAPH[_cb0:_cb0 + 1400])

# ⑨ 离线可验的"专家 vs 裸 LLM"差异：证据包里装着裸 LLM 拿不到的数字
# ⚠️ 下面这组是**自洽 fixture**（输入→本文件自己的断言），取自 2026-09-16 口径的案例 F
#    （品牌 uplift v1：蜜雪 1.1343）。2026-09-18 uplift 整表重标定到 v6 后真机值为
#    地址评分 86.1 / 经营评分 76 / 盈亏平衡月租 24,700 / 回本上限 21,900 / 月净利 12,688。
#    这里**不追实机**（断言只要求 pack 里出现 fixture 自己的数），改它没有收益；
#    但要知道它不代表当前引擎输出，别拿它当"当前口径"引用。
_fake = {'category': '奶茶', 'name': 'X', 'city': '宁波', 'monthly_rent': 12000,
         'area_m2': 30, 'total': 85.8, 'verdict': '谨慎推荐',
         'dims': {'竞争压力': 77}, 'veto': {'触发': False, '位置分结论': '推荐'},
         'rent_limits': {'盈亏平衡月租': 22250, '回本达标月租上限': 19450},
         '经营评分': {'分数': 70},
         'profit': {'月净利估算': 10265, '月成本合计': 40000, '月固定成本': 40000},
         'profit_bands': {'乐观': {'月净利估算': 25482}, '中性': {'月净利估算': 10265},
                          '保守': {'月净利估算': -2677}, '区间': {'结论': '情景敏感'}},
         '客单价校正': {'校正客单价': 11.4, '每单金额口径来源': 'public_report'}}
_pack = _bep({'score_result': _fake})
check('证据包含"裸 LLM 不可能知道"的关键数字（经营评分/回本上限/三档/盈亏平衡）',
      all(s in _pack for s in ('19450', '22250', '70', '25482', '-2677')),
      _pack[:80])
check('证据包丢掉已废弃别名「月固定成本」（同一问题：prompt 不留冗余）',
      '月固定成本' not in _pack and '月成本合计' in _pack)
check('证据包给的是摘要而非整份成本字典（§4 同一问题）',
      len(_pack) < len(__import__('json').dumps(_fake, ensure_ascii=False)))
check('缺的字段直接省略、不写"暂无"占位（免得模型读成 0）',
      '暂无' not in _bep({'score_result': {'category': '奶茶'}}))
check('无分析结果时证据包为空串（逐字走回旧路径）',
      _bep({}) == '' and _bep({'score_result': {}}) == '')

# =====================================================================
# §9 LLM 信息性（默认不跑，不进离线门禁）
# =====================================================================
p('')
p('=== §9 LLM 信息性（VERIFY_EXPERTS_LLM=1 才跑；网络依赖，不计门禁）===')
if os.environ.get('VERIFY_EXPERTS_LLM') != '1':
    p('  ---- 跳过（未设 VERIFY_EXPERTS_LLM=1）')
else:
    import agent.llm as LLM

    async def _real_case(system_id, user):
        sysp = R.compose_system_prompt(system_id)
        return await LLM.call_llm(sysp, user, temperature=0.3, timeout=120)

    async def _llm_cases():
        rent = await _real_case(
            'rent_negotiator',
            '我这家铺子月租 1.2 万，可承受月租上限引擎算出来是 1.5 万，'
            '帮我准备跟房东谈的话术。')
        diag = await _real_case(
            'store_diagnosis_advisor',
            '我奶茶店月流水 8 万、月租 1.2 万、30㎡，帮我诊断。'
            '数据：毛利率 65%、扣渠道后 57.3%、净利率 11.4%、'
            '盈亏平衡月流水 61,600、安全边际率 23%。')
        return rent, diag

    try:
        _rent_txt, _diag_txt = asyncio.run(_llm_cases())
        bad_open = [w for w in ('先出', '目标价') if w in _rent_txt]
        info('谈判教练输出不把天花板当开价',
             not bad_open, f'命中={bad_open}；字数={len(_rent_txt)}')
        info('谈判教练输出含"挂牌/成交"提醒',
             any(k in _rent_txt for k in ('挂牌', '成交')), f'字数={len(_rent_txt)}')
        info('经营测算输出不出现"预估月流水"',
             '预估月流水' not in _diag_txt, f'字数={len(_diag_txt)}')
    except Exception as e:
        info('LLM 用例执行', False, f'{type(e).__name__}: {e}')

# =====================================================================
p('')
p('=' * 66)
p(f'FAILED = {len(FAIL)}' + (f'   信息性未达 = {len(INFO)}' if INFO else ''))
for f in FAIL:
    p('  - ' + f)
p('=' * 66)
OUT.write_text('\n'.join(L), encoding='utf-8')
sys.exit(1 if FAIL else 0)
