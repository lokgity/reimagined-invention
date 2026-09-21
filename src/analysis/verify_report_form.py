# -*- coding: utf-8 -*-
"""verify_report_form.py —— 《店铺经营月报》表单可读性门禁
==========================================================================
桌面那份《店铺经营月报》是**给人填、给机器读**的表：用户填完直接上传，或把
第四章那段摘要复制进对话，`diagnose_node` 用 `extract_*` / `_parse_*` 把它拆成
经营测算专家的输入。所以这张表有一个**硬约束**：

  ⚠️ 表上**不能出现任何数字**（ASCII 或全角）。
     一旦印了示例数字，用户没填的那一栏会命中示例值 —— 例子会被当成真实流水
     算进诊断，正是项目纪律里最不能接受的那种"认错还不报错"。同理，凡是
     排在用户填写位置**之前**的数字都可能抢到首匹配（`extract_*` 用 `.search`，
     首个命中即采信）。所以规则是一刀切：表体零数字。

本套件把这条约束 + 表单与抽取器的**口径对齐**锁死：

  §1 源表零数字（含全角），且填写位是 U+3000 空白段（不是下划线：
     下划线会挡住 `_parse_investment` 的 `[:：]?\\s*`，用户把数字写在空白段
     尾部时投入会被静默丢掉，回本周期整条不可信）。
  §2 抽取器逐项对齐：十项输入按"用户把数字写在标签后"的两种常见落笔位置
     （顶格写 / 写在空白段末尾）都必须解出同一个值。
  §3 两条喂入路径等价：① 只填第二/三章（上传 docx）② 只填第四章摘要（粘一段话）。
     并按 `_extract_docx` 的真实行为**先段落、后表格**模拟 Word 抽取顺序
     （python-docx 的 `d.paragraphs` 不含表格内段落 → 段落永远排在表格前），
     确认附录成本表不会反过来污染上面填的值。
  §4 摘要句与表单一致时以摘要为准（首匹配），且**表单全空时不得从表头/说明
     文字里凭空解出任何数** —— 空表必须解出全 None，逼出"继续追问"而不是猜。
  §5 交付面 HTML（Stage 2 产物，docx 的直接输入）与 md 同源：可见文本同样零数字、
     十个标签齐全、填写位够用，且**两种落笔位置都解得对**。md 只是中间稿，用户
     真正拿到手的是 docx，所以 HTML 这一层必须单独验，不能只验 md。
  §6 **填写样例**（`docs/店铺经营月报-样例.md` / `.html`，随空白表一起交付的那份）：
     与 `report_sample.py` 的构造结果逐字节一致（防手工改了样例、数据源没跟着改），
     且 md / html 两条路的可见文本用真实抽取器都能解出十项 —— 样例里印着数字，
     所以这一节验的正是**"印出来的数会不会把用户填的数抢走"**：附录自查表填了数，
     但表格永远排在段落之后，不得顶掉表体里填的值。

⚠️ 填写位宽度不是随便定的。抽取器给"标签→数字"之间留的空档是有限的：
     extract_area      [^\d]{0,4}    ← 最紧
     _parse_price      [^\d]{0,4}    ← 最紧
     extract_rent      [^\d]{0,6}
     extract_monthly_revenue [^\d]{0,6}
     _parse_daily_orders     [^\d]{0,6}?
     _parse_investment       [:：]?\s*   （\s 认得 U+3000，宽窄无所谓）
     _parse_staff            (\d+)\s*(?:人|名…)   数字在前，无所谓
   所以"标签 + 冒号 + N 个全角空格"必须满足 N ≤ 3 —— 填 4 个空格，用户把数字写在
   空白段末尾时，`面积`/`每单金额` 就会静默取不到值。§2/§5 的 tail 模式就是钉这条。

用法：C:\\Python314\\python.exe src/analysis/verify_report_form.py
输出：同目录 _verify_report_form.txt
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / '.pylibs'))
sys.path.insert(0, str(HERE))              # report_sample 与本文件同目录

L, FAIL = [], []
OUT = HERE / '_verify_report_form.txt'

# ⚠️ "什么算填写位"的规则**只有一份**，在 `report_sample.py` 里（填充原语与
#    render/html_text 都在那儿）。本门禁 import 它，而不是自己再抄一套 ——
#    否则生成器改了规则、门禁还按老规则放行，正是这个项目最怕的"静默失效"。
from report_sample import (                # noqa: E402
    BLANK, SUMMARY_MARK, SAMPLE, APPENDIX,
    fill, fill_summary, blank_span, labeled_slots, render_markdown, html_text,
    build_sample_md, build_sample_html,
    BLANK_MD, BLANK_HTML, SAMPLE_MD, SAMPLE_HTML,
    SAMPLE_HEADER_HTML, SAMPLE_HEADER_MD,
)

FORM = BLANK_MD
FORM_HTML = BLANK_HTML


def p(*a):
    s = ' '.join(str(x) for x in a)
    print(s)
    L.append(s)


def check(name, cond, detail=''):
    p(f'  {"PASS" if cond else "FAIL"}  {name}' + (f'  |  {detail}' if detail else ''))
    if not cond:
        FAIL.append(name)


# ---------------------------------------------------------------- 模拟
def sim_docx_order(rendered: str) -> str:
    """模拟 `app_chainlit._extract_docx` 的抽取顺序：**先全部段落，再全部表格**。

    python-docx 的 `Document.paragraphs` 不含表格单元格里的段落，所以真实
    抽取出来的顺序是"文档里所有段落"在前、"所有表格行"在后 —— 与文档里的
    视觉顺序无关。这条顺序差正是"附录表格里的数字会不会抢到首匹配"的判据，
    必须照它模拟，不能按视觉顺序模拟。
    """
    paras, tables, cur = [], [], None
    for line in rendered.splitlines():
        s = line.strip()
        if s.startswith('|'):
            cells = [c.strip() for c in s.strip('|').split('|')]
            if set(''.join(cells)) <= set('-: '):      # 表格分隔行
                continue
            if cur is None:
                cur = []
                tables.append(cur)
            cur.append(' | '.join(cells))
        else:
            cur = None
            paras.append(s)
    return '\n'.join(paras + [r for tb in tables for r in tb])


# 填充原语（render_markdown / html_text / blank_span / fill / fill_summary）
# 已移到 report_sample.py 并在文件头 import —— 只留一份实现。


# ---------------------------------------------------------------- 抽取器
from agent.agent import (                       # noqa: E402
    extract_category, extract_rent, extract_monthly_revenue,
    extract_area, extract_brand,
)
from agent.agent_graph import (                 # noqa: E402
    extract_city, _parse_staff, _parse_investment,
    _parse_price, _parse_daily_orders,
)

# 十项输入 × 各自的抽取器。⚠️ 数值直接取 `report_sample.SAMPLE`（= 交付样例里
# 印着的那组数）——门禁就按用户真会看到的数字验，不另编一套。
_EXTRACTOR = {
    '品类': extract_category,
    '月流水': extract_monthly_revenue,
    '月租金': extract_rent,
    '经营面积': extract_area,
    '店铺所在城市': extract_city,
    '加盟品牌': extract_brand,
    '全职员工': _parse_staff,
    '前期投入': None,               # 走 _parse_investment(strict=True)，见 run_extractors
    '每单金额': _parse_price,
    '日单量': _parse_daily_orders,
}
FIELDS = [(lb, val, _EXTRACTOR[lb], exp) for lb, val, exp in SAMPLE]


def run_extractors(text: str) -> dict:
    got = {name: fn(text) for name, _, fn, _ in FIELDS if fn}
    got['前期投入'] = _parse_investment(text, strict=True)
    return got


def main():
    p('=' * 74)
    p('《店铺经营月报》表单可读性门禁')
    p('=' * 74)
    p(f'表单源: {FORM.relative_to(ROOT)}')

    if not FORM.exists():
        check('表单源存在', False, f'找不到 {FORM}')
        OUT.write_text('\n'.join(L), encoding='utf-8')
        return 1
    md = FORM.read_text(encoding='utf-8')
    rendered = render_markdown(md)

    # ---------------- §1 零数字 + 填写位类型 ----------------
    p('')
    p('§1 表体零数字（防"示例值被当成真实数据"）')
    digits = sorted({ch for ch in md if ch.isdigit()})
    check('表体不含任何数字（ASCII / 全角）', not digits,
          f'发现的数字字符: {digits}' if digits else '零数字')
    check('填写位用 U+3000 空白段（不是下划线）',
          '\u3000' in md and not re.search(r'_{2,}', md),
          f'U+3000 段数={len(re.findall(chr(0x3000) + "+", md))}'
          f'，下划线段数={len(re.findall(r"_{2,}", md))}')
    n_blank = len(re.findall('\u3000+', md))
    check('填写位数量覆盖十项输入（表单 + 摘要各一套）', n_blank >= 20,
          f'空白段共 {n_blank} 处')

    # ---------------- §2 逐项口径对齐（两种落笔位置） ----------------
    for mode in ('head', 'tail'):
        p('')
        p(f'§2 抽取器口径对齐 —— 数字{"顶格写" if mode == "head" else "写在空白段末尾"}')
        body = rendered
        for label, value, _, _ in FIELDS:
            body = fill(body, label, value, mode=mode)
        got = run_extractors(body)
        for label, value, _, expect in FIELDS:
            check(f'{label} → {expect!r}', got[label] == expect,
                  f'实得 {got[label]!r}')

    # ---------------- §3 两条喂入路径等价 ----------------
    p('')
    p('§3 两条喂入路径等价（上传 docx / 粘一段话）')

    # ① 只填第二、三章（= 用户上传填好的 docx）
    up = rendered
    for label, value, _, _ in FIELDS:
        up = fill(up, label, value)
    up_docx = sim_docx_order(up)          # 附录成本表若填了，也在表格里排后面
    up_docx_filled = fill(up_docx, '员工工资', '6000')
    got_up = run_extractors(up_docx_filled)
    for label, value, _, expect in FIELDS:
        check(f'上传路径·{label}', got_up[label] == expect, f'实得 {got_up[label]!r}')

    # ② 只填第四章摘要（= 用户复制一段话）—— 表单留空，只在摘要句里写数
    paste = fill_summary(rendered, [v for _, v, _, _ in FIELDS])
    got_paste = run_extractors(paste)
    for label, value, _, expect in FIELDS:
        check(f'粘贴路径·{label}', got_paste[label] == expect, f'实得 {got_paste[label]!r}')

    # ---------------- §4 空表必须解不出，不许猜 ----------------
    p('')
    p('§4 空表/半填行为（不许拿表头说明文字凑数）')
    empty = run_extractors(sim_docx_order(rendered))
    check('全空表 → 十项全 None（逼出追问，而不是猜）',
          all(v is None for v in empty.values()),
          f'实得 {empty}')

    half = fill(rendered, '品类', '奶茶')
    half = fill(half, '月流水', '135000')
    got_half = run_extractors(sim_docx_order(half))
    check('只填品类+月流水 → 月租金为 None（不拿别的数顶上）',
          got_half['月租金'] is None and got_half['月流水'] == 135000,
          f'实得 {got_half}')

    # ---------------- §5 交付面 HTML（docx 的直接输入） ----------------
    p('')
    p('§5 交付面 HTML 与 md 同源（md 只是中间稿，用户真正拿到的是 docx）')
    if not FORM_HTML.exists():
        check('HTML 交付源存在', False, f'找不到 {FORM_HTML}')
    else:
        ht = html_text(FORM_HTML.read_text(encoding='utf-8'))
        hd = sorted({c for c in ht if c.isdigit()})
        check('HTML 可见文本零数字', not hd, f'发现 {hd}' if hd else '零数字')
        miss = [lb for lb, *_ in FIELDS if lb not in ht]
        check('HTML 十个口径标签齐全', not miss, f'缺 {miss}' if miss else '齐全')
        nbh = len(re.findall('\u3000+', ht))
        check('HTML 填写位够用（表单 + 摘要 + 附录）', nbh >= 25, f'{nbh} 处')
        check('HTML 含第四章摘要行（用户唯一要复制的那行）', SUMMARY_MARK in ht)
        for mode in ('head', 'tail'):
            hf = ht
            for label, value, _, _ in FIELDS:
                hf = fill(hf, label, value, mode=mode)
            gh = run_extractors(hf)
            bad = [lb for lb, _, _, ex in FIELDS if gh[lb] != ex]
            check(f'HTML 数字{"顶格写" if mode == "head" else "写在空白段末尾"} → 十项全对',
                  not bad, f'错项 {bad}（实得 {gh}）' if bad else '')
        hp = fill_summary(ht, [v for _, v, _, _ in FIELDS])
        gp = run_extractors(hp)
        badp = [lb for lb, _, _, ex in FIELDS if gp[lb] != ex]
        check('HTML 只填摘要 → 十项全对', not badp,
              f'错项 {badp}（实得 {gp}）' if badp else '')

    # ---------------- §6 填写样例（随空白表一起交付的那份） ----------------
    p('')
    p('§6 填写样例：交付面（html）与中间稿（md）都能被真实抽取器读全')
    miss_src = [str(x.relative_to(ROOT)) for x in (SAMPLE_MD, SAMPLE_HTML)
                if not x.exists()]
    check('样例 md / html 都已生成', not miss_src,
          f'缺 {miss_src}（跑 src/analysis/make_sample_report.py）' if miss_src else '')
    if not miss_src:
        smd = SAMPLE_MD.read_text(encoding='utf-8')
        sht = SAMPLE_HTML.read_text(encoding='utf-8')
        # ① 与构造器逐字节一致：防止"手工改了样例、数据源没改"这种漂移
        check('样例 md 与 report_sample 构造结果逐字节一致',
              smd == build_sample_md(BLANK_MD.read_text(encoding='utf-8')))
        check('样例 html 与 report_sample 构造结果逐字节一致',
              sht == build_sample_html(BLANK_HTML.read_text(encoding='utf-8')))
        # ② 标注：让人一眼看出这不是空白表，且标注里不许混进会污染抽取的东西
        hdr_ok = ('填写样例' in sht) and ('填写样例' in smd)
        check('样例明写「填写样例」（不会被当成空白表误用）', hdr_ok)
        # ③ 说明块本身不许含 U+3000 —— 它会被 blank_span 当成填写位。
        #    （整份文档里当然还有 U+3000：章节标题 `第一章　怎么用`、副标题分隔符、
        #      CSS 页脚，那些跟口径标签不在同一行，labeled_slots 不会认。）
        check('样例说明块不含全角空格（会被当成填写位）',
              '\u3000' not in SAMPLE_HEADER_HTML + SAMPLE_HEADER_MD)
        # ④ 填写位账要平：空白表 28 个（十项 + 摘要十项 + 附录八行），样例必须 0 个。
        #    "有几个位、填了几个"这件事只能这样逐位对，不能靠"看着像填了"。
        LABELS = [x[0] for x in FIELDS] + [n for n, _ in APPENDIX]
        for tag, blank_text, sample_text in (
                ('html', html_text(BLANK_HTML.read_text(encoding='utf-8')),
                 html_text(sht)),
                ('md', render_markdown(BLANK_MD.read_text(encoding='utf-8')),
                 render_markdown(smd))):
            n_blank = len(labeled_slots(blank_text, LABELS))
            left = [lb for lb, _ in labeled_slots(sample_text, LABELS)]
            check(f'样例·{tag} 空白表 {n_blank} 个填写位 → 样例里 0 个残留',
                  n_blank == 28 and not left,
                  f'空白表 {n_blank} 个（应 28）；样例残留 {left}')
        # ⑤ 十项必须全中 —— md 走 render_markdown，html 走 html_text，
        #    两条路都按 `_extract_docx` 的"段落在前"顺序铺开
        got_md = run_extractors(sim_docx_order(render_markdown(smd)))
        got_ht = run_extractors(html_text(sht))
        for lb, _, _, ex in FIELDS:
            check(f'样例·md {lb} → {ex!r}', got_md[lb] == ex, f'实得 {got_md[lb]!r}')
            check(f'样例·html {lb} → {ex!r}', got_ht[lb] == ex, f'实得 {got_ht[lb]!r}')
        # ⑥ 附录自查表填了数，但不能反向污染上面十项（表格永远排在段落之后）
        ap_ok = all(v in sht for _, v in APPENDIX)
        check('附录成本自查表已填（含合计）', ap_ok)
        exp_rev = dict((lb, ex) for lb, _, ex in SAMPLE)['月流水']
        exp_rent = dict((lb, ex) for lb, _, ex in SAMPLE)['月租金']
        check('附录表格数字未抢走首匹配（月流水仍是表体里那个）',
              got_ht['月流水'] == exp_rev and got_ht['月租金'] == exp_rent,
              f'实得 {got_ht["月流水"]!r} / {got_ht["月租金"]!r}')

    p('')
    p('=' * 74)
    p(f'结论：{"全部通过" if not FAIL else str(len(FAIL)) + " 项未过"}'
      f'（断言 {len(L) - 1} 条，失败 {len(FAIL)} 条）')
    p(f'FAILED={len(FAIL)}')        # 门禁 runner 的计数标记（与其它套件同格式）
    if FAIL:
        for f in FAIL:
            p(f'  ✗ {f}')
    OUT.write_text('\n'.join(L), encoding='utf-8')
    return 0 if not FAIL else 1


if __name__ == '__main__':
    sys.exit(main())
