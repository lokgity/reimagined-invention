# -*- coding: utf-8 -*-
"""
registry.py —— 专家注册表（运行时唯一入口）
================================================
把 `src/experts/*.md` 的 frontmatter 变成**可编程对象**：

    registry.list_experts()                    -> 可选专家列表（已按组与 order 排好）
    registry.get_expert('rent_negotiator')     -> 单个专家
    registry.expert_choices()                  -> Chainlit 首屏卡片用的精简列表
    registry.common_laws()                     -> _common.md 的公共铁律正文
    registry.compose_system_prompt(expert_id)  -> 最终 system prompt（公共铁律 + 专家增量）

三个设计约束（都是踩过坑才写下来的）：

1. **单一真源**：frontmatter schema 与工具词汇表定义在本模块，
   `validate_design.py` 从本模块 import 这些常量。两份规则必然漂移，一份不会。
   （历史：`validate_design.py` 的校验规则自己出过 bug —— 把 `requires: []`
   这种"零依赖"的正当写法误判成缺必填。规则也需要被验证，所以只留一份。）

2. **加载即校验，失败即抛**：字段非法时抛 `ExpertConfigError`，
   **不静默跳过**。理由：专家定义写错了却照常启动，比启动失败危险得多 ——
   用户看到的是"这个专家说的话不对"，而不是"配置有问题"，
   排查成本差一个量级。错误一次性全列出，不挤牙膏。

3. **公共铁律只有一份**：`compose_system_prompt` 每次都从 `_common.md` 现读，
   9 份专家 md 里**没有**任何一条铁律的副本。
   （这是本项目最容易做砸的地方：`interpret_node` 原有 9 条约束被 4 个节点共用，
   若拆成 9 份复制品，改一次要改 9 处，必然漏。）

用法：
    from experts import registry
    ex = registry.get_expert('site_advisor')
    sys_prompt = registry.compose_system_prompt('site_advisor')
"""
import sys
from pathlib import Path

try:
    import yaml
except ImportError:                     # 独立跑（未经 _run.py / 未设 PYTHONPATH）时的兜底
    _root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(_root / '.pylibs'))
    import yaml

HERE = Path(__file__).resolve().parent

# 工具词汇表：`tools` / `forbids` 只能取这些名字。
# 它不是为了拦用户，而是让"专家"有**可验证差异**：
# 谈判教练不调 analyze_storefront、门头审核员不调 diagnose_existing_store ——
# 这些差异是能测出来的，而"换了个人设"是测不出来的。
VOCAB = {
    'score_site', 'elasticity_band', 'solve_rent_limits', 'compare_sites',
    'apply_storefront', 'estimate_profit', 'estimate_profit_bands',
    'estimate_monthly_utility', 'reverse_match', 'competitor_brief',
    'brand_price_reference', 'analyze_competitors', 'negotiation_brief',
    'rent_benchmark', 'fetch_shops', 'get_franchise_info', 'supported_brands',
    'brand_store_metrics', 'brand_order_value', 'brand_uplift',
    'brand_uplift_detail', 'brand_attractiveness', 'is_self_brand',
    'analyze_storefront', 'diagnose_existing_store', 'brand_benchmark',
    'get_material_ratio', 'get_delivery_ratio', 'kb_retrieve',
    'list_analyses', 'add_analysis', 'rule_based_interpret', 'geocode',
}

# 必填字段。注意 `requires` **允许空列表**（= 零数据依赖，model_auditor 的正当用法）：
# 键必须在，但值可以为空。当初就是把"值空"和"键缺"混为一谈才误报了。
#
# `alias` / `blurb` 是 2026-09-16 为「专家系统」卡片页新增的**展示字段**：
#   alias = 人名（用户记住一个人比记住一个岗位名容易）
#   blurb = 2-3 句"我到底帮你做什么"（one_liner 只有一句，撑不起卡片页）
# 之所以升为必填而不是可选：卡片页若缺这两项会退化成"只有岗位名"，
# 那就又变回"换个人设的幌子"了 —— 缺了就该在启动时大声失败。
REQUIRED = ['id', 'name', 'alias', 'blurb', 'group', 'order', 'one_liner',
            'start_sentence', 'requires', 'tools', 'output_contract',
            'fallback', 'status']

GROUPS = ('开店前决策链', '开店后', '阶段无关')

# 九位专家定稿清单。多一个少一个都要报错 —— 这是"设计稿"与"实现"对账的锚点。
EXPECTED_IDS = {
    'site_advisor', 'category_reverse', 'competitor_analyst',
    'rent_negotiator', 'storefront_auditor', 'startup_policy_advisor',
    'store_diagnosis_advisor', 'franchise_advisor', 'model_auditor',
}

COMMON_ID = '_common'
VALID_STATUS = ('ready', 'blocked')


class ExpertConfigError(RuntimeError):
    """专家定义不合法。一次性列出全部问题，不挤牙膏。"""


class Expert:
    """一位专家 = 一份 md 的 frontmatter（结构化字段）+ 正文（人设与增量职责）。"""

    __slots__ = ('id', 'name', 'alias', 'blurb', 'icon', 'group', 'order',
                 'one_liner', 'start_sentence', 'requires', 'requires_absent',
                 'optional', 'tools', 'forbids', 'kb_tags', 'node', 'fallback',
                 'output_contract', 'assertions', 'status', 'persona', 'path',
                 'live_facts')

    def __init__(self, meta, body, path):
        for k in ('id', 'name', 'alias', 'blurb', 'icon', 'group', 'order',
                  'one_liner', 'start_sentence', 'requires', 'tools',
                  'output_contract', 'fallback', 'status'):
            setattr(self, k, meta.get(k))
        self.requires_absent = meta.get('requires_absent') or []
        self.optional = meta.get('optional') or []
        self.forbids = meta.get('forbids') or []
        self.kb_tags = meta.get('kb_tags') or []
        self.node = meta.get('node')
        self.assertions = meta.get('assertions') or []
        # live_facts：声明式"把 `agent/model_facts.py` 的实时数据块注入我的 system prompt"。
        # 存在的理由（2026-09-18）：模型审计师的人设原来是**把标定数字写死在 md 里**的，
        # 样本一扩、口径一变，人设里的话就过期了，而且是**静默过期**（没人会去 grep md）。
        # true = 全部块；也可是块名列表（如 [锚点] 只要锚点那块）。
        self.live_facts = meta.get('live_facts')
        self.persona = body.strip()
        self.path = path

    @property
    def selectable(self) -> bool:
        """blocked 的专家不得出现在用户可选列表（README §三.5）。"""
        return self.status == 'ready'

    def card(self) -> dict:
        """给 UI（首屏 / 输入框上方面板 / 左侧卡片页）用的精简结构。

        不含 persona —— 卡片不该带几千字。含 `alias` / `blurb`：
        前者让用户记得住人，后者撑得起卡片页的"详细解释"。
        """
        return {'id': self.id, 'name': self.name, 'alias': self.alias,
                'blurb': self.blurb, 'icon': self.icon, 'group': self.group,
                'order': self.order, 'one_liner': self.one_liner,
                'start_sentence': self.start_sentence}

    def __repr__(self):
        return f'<Expert {self.id} {self.name!r} {self.status}>'


def _split(path: Path):
    txt = path.read_text(encoding='utf-8')
    if not txt.startswith('---\n'):
        raise ValueError('缺少 frontmatter（文件必须以 --- 开头）')
    parts = txt.split('---\n', 2)
    if len(parts) < 3:
        raise ValueError('frontmatter 未正确闭合（缺少第二个 --- 行）')
    meta = yaml.safe_load(parts[1])
    if not isinstance(meta, dict):
        raise ValueError('frontmatter 不是 mapping')
    return meta, parts[2]


def _facts_blocks():
    """`agent/model_facts.py` 的块名集合（懒加载）。取不到返回 None，不阻断启动。

    刻意**不**在本模块里再抄一份块名清单：两份清单必然漂移，而漂移的后果是
    "专家声明了一个不存在的块、静默什么也没注入" —— 正是本项目最怕的静默失败。
    """
    try:
        if str(HERE.parent) not in sys.path:
            sys.path.insert(0, str(HERE.parent))
        from agent.model_facts import BLOCKS
        return set(BLOCKS)
    except Exception:                      # noqa: BLE001
        return None


def collect_errors() -> list:
    """扫描并校验全部专家文件，返回错误清单（空列表 = 全部合法）。

    `validate_design.py` 与本模块的 `load_experts()` 共用这一份规则。
    """
    fails, seen = [], {}
    seen_alias = {}
    for p in sorted(HERE.glob('*.md')):
        if p.name == 'README.md':
            continue
        try:
            meta, _body = _split(p)
        except Exception as e:
            fails.append(f'{p.name}: frontmatter 解析失败：{e}')
            continue
        if p.name == f'{COMMON_ID}.md':
            if meta.get('id') != COMMON_ID:
                fails.append(f'{p.name}: id 必须是 {COMMON_ID}')
            continue

        for k in REQUIRED:
            if k not in meta:
                fails.append(f'{p.name}: 缺必填字段 {k}')
            elif k != 'requires' and meta[k] in (None, '', []):
                fails.append(f'{p.name}: 字段 {k} 为空')

        if meta.get('id') != p.stem:
            fails.append(f'{p.name}: id({meta.get("id")!r}) != 文件名({p.stem!r})')
        if meta.get('id') in seen:
            fails.append(f'{p.name}: id 与 {seen[meta.get("id")]} 重复')
        seen[meta.get('id')] = p.name

        # 人名必须唯一：两位专家同名，用户就分不清刚才切给谁了。
        # （人名是"给人记的"，id 是"给机器认的"，两者都要唯一。）
        alias = str(meta.get('alias') or '').strip()
        if alias:
            if alias in seen_alias:
                fails.append(f'{p.name}: 人名 «{alias}» 与 {seen_alias[alias]} 重复')
            seen_alias[alias] = p.name

        if meta.get('group') not in GROUPS:
            fails.append(f'{p.name}: group 非法 {meta.get("group")!r}')
        if meta.get('status') not in VALID_STATUS:
            fails.append(f'{p.name}: status 非法 {meta.get("status")!r}')
        if meta.get('requires') and not str(meta.get('fallback') or '').strip():
            fails.append(f'{p.name}: requires 非空但 fallback 为空')
        for f in ('tools', 'forbids'):
            for t in (meta.get(f) or []):
                if t not in VOCAB:
                    fails.append(f'{p.name}: {f} 含未登记工具 «{t}»')

        # live_facts 校验（懒加载 model_facts 取块名，避免"两份清单各自漂移"）
        lf = meta.get('live_facts')
        if lf not in (None, False):
            if lf is not True and not isinstance(lf, list):
                fails.append(f'{p.name}: live_facts 必须是 true 或块名列表，'
                             f'实际 {lf!r}')
            elif isinstance(lf, list):
                known = _facts_blocks()
                if known is None:
                    fails.append(f'{p.name}: live_facts 非空但 model_facts 加载不到，'
                                 f'无法校验块名')
                else:
                    bad = [b for b in lf if b not in known]
                    if bad:
                        fails.append(f'{p.name}: live_facts 含未登记块名 {bad}'
                                     f'（可用：{sorted(known)}）')

    missing = EXPECTED_IDS - set(seen)
    extra = set(seen) - EXPECTED_IDS
    if missing:
        fails.append(f'缺专家文件：{sorted(missing)}')
    if extra:
        fails.append(f'出现未登记的专家：{sorted(extra)}')
    return fails


_CACHE = None


def load_experts(force: bool = False) -> dict:
    """加载全部专家 → {id: Expert}。校验不过则抛 ExpertConfigError。"""
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE
    fails = collect_errors()
    if fails:
        raise ExpertConfigError(
            f'专家定义有 {len(fails)} 处问题，已拒绝启动：\n  - ' + '\n  - '.join(fails))
    out = {}
    for p in sorted(HERE.glob('*.md')):
        if p.name in ('README.md', f'{COMMON_ID}.md'):
            continue
        meta, body = _split(p)
        out[meta['id']] = Expert(meta, body, p)
    _CACHE = out
    return out


_GROUP_ORDER = {g: i for i, g in enumerate(GROUPS)}


def list_experts(include_blocked: bool = False) -> list:
    """按「开店前决策链 → 开店后 → 阶段无关」、组内按 order 排序。"""
    ex = list(load_experts().values())
    if not include_blocked:
        ex = [e for e in ex if e.selectable]
    return sorted(ex, key=lambda e: (_GROUP_ORDER.get(e.group, 99), e.order))


def get_expert(expert_id: str) -> Expert:
    """取单个专家。id 不存在时抛 ExpertConfigError（带可用 id 列表，便于排查）。"""
    ex = load_experts()
    if expert_id not in ex:
        raise ExpertConfigError(
            f'未知专家 id={expert_id!r}，可用：{sorted(ex)}')
    return ex[expert_id]


def expert_choices() -> list:
    """给 UI 的精简列表：[{id,name,icon,group,one_liner,start_sentence}, ...]"""
    return [e.card() for e in list_experts(include_blocked=False)]


def by_group() -> dict:
    """{组名: [Expert, ...]}，供首屏按组渲染。"""
    out = {}
    for e in list_experts(include_blocked=False):
        out.setdefault(e.group, []).append(e)
    return out


# ---------------------------------------------------------------
# prompt 组装（P1：公共铁律 1 份 + 专家增量）
# ---------------------------------------------------------------
def common_laws() -> str:
    """`_common.md` 的**正文**（去掉开头的引用说明块）。

    去掉那段 `>` 说明是有意的：那里写的是"给维护者看的拼装契约"
    （比如"泛化时不得放宽语义"），不该占 LLM 的上下文。
    正文从第一个二级标题开始。
    """
    _meta, body = _split(HERE / f'{COMMON_ID}.md')
    i = body.find('## ')
    core = body[i:] if i >= 0 else body
    return '以下是所有专家都必须遵守的铁律（与你的人设冲突时，以铁律为准）：\n\n' + core.strip()


def _live_facts_text(live_facts) -> str:
    """取实时事实块文本。**取不到就如实说取不到，绝不回落写死值**（红线 1）。"""
    try:
        if str(HERE.parent) not in sys.path:
            sys.path.insert(0, str(HERE.parent))
        from agent.model_facts import render_for_prompt
        blocks = None if live_facts is True else list(live_facts)
        return render_for_prompt(blocks=blocks)
    except Exception as e:                 # noqa: BLE001
        return ('【本模型实时事实：本次读取失败（%s）——**不要凭记忆引用锚点、'
                '样本量、系数数值**，如实告诉用户当前取不到即可】'
                % type(e).__name__)


def compose_system_prompt(expert_id: str, kb_text: str = '',
                          with_facts: bool = True) -> str:
    """拼最终 system prompt = 公共铁律（唯一一份）+ 该专家的 persona 增量 + 实时事实块。

    ⚠️ **不要在这里复制铁律**。想改铁律只改 `_common.md` 一个文件。
    专家的 persona 只写"我比铁律多做什么"（角色、读哪些字段、输出契约、禁止项）。

    `kb_text` 是该专家的分区检索结果（可为空串）。
    `live_facts`（frontmatter 字段）非空的专家，会把 `agent/model_facts.py` 的
    实时数据块插在 persona 之后 —— 这样人设里就不必（也不许）再写死标定数字。
    `with_facts=False` 供"只想看铁律+persona"的调用方/断言用。
    """
    ex = get_expert(expert_id)
    parts = [common_laws(),
             '',
             '=' * 20 + ' 你现在的角色 ' + '=' * 20,
             ex.persona]
    if ex.live_facts and with_facts:
        blk = _live_facts_text(ex.live_facts)
        if blk:
            parts += ['', blk]
    if kb_text:
        parts += ['', '【知识库检索结果（本地知识库，可参考；用到时自然融入，不要照抄条目编号）】',
                  kb_text]
    return '\n'.join(parts)


def persona_only(expert_id: str) -> str:
    """只要专家 persona（不含公共铁律）。给"铁律已由调用方单独给出"的场景用。"""
    return get_expert(expert_id).persona


if __name__ == '__main__':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    print('=' * 66)
    print('专家注册表')
    print('=' * 66)
    for grp, items in by_group().items():
        print(f'\n[{grp}]')
        for e in items:
            print(f'  {e.order}. {e.alias}·{e.name:<8} {e.id:<24} '
                  f'tools={len(e.tools)} kb_tags={e.kb_tags}')
    print(f'\n可选专家 = {len(expert_choices())}　全部（含 blocked） = '
          f'{len(list_experts(include_blocked=True))}')
    print(f'公共铁律字数 = {len(common_laws())}')
    print(f'site_advisor 完整 prompt 字数 = {len(compose_system_prompt("site_advisor"))}')
