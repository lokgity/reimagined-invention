# -*- coding: utf-8 -*-
"""report_sample.py —— 《店铺经营月报》**填写样例**的唯一数据源与构造器
==========================================================================
背景：桌面那份《店铺经营月报》（`docs/店铺经营月报-表单.md` / `.html`）是**空白表**。
空白表把"不许印示例数字"钉死了（见 `verify_report_form.py` 顶部），代价是用户第一次
拿到手时不知道**填成什么颗粒度**。所以再交付一份**填好的样例**：

    docs/店铺经营月报-样例.md / .html  →  C:\\Users\\ASUS\\Desktop\\店铺经营月报-填写样例.docx

这个文件是那份样例的**唯一数据源**，被三处共用，保证不会各改各的：

    make_sample_report.py   照它生成 md / html
    verify_report_form.py   §6 静态验样例（用真实抽取器解样例 HTML）
    live_report_probe.py    --sample 实机验成品 docx

⚠️ 样例里的数字是**编的**，但必须同时满足三件事：

  1. **能被抽取器读全**（这决定它到底有没有用）—— 十项一项不漏。
     `_parse_investment(strict=True)` 尤其脆：它有命名口径表，裸"X万"不认，
     而"月流水/S 万"这类句子必须先被掩码挖掉，否则投入会被读成流水。
  2. **算术自洽** —— 日单量 × 每单金额 × 30 ≈ 月流水（300 × 15 × 30 = 135000）。
     样例是给人照抄的，自洽才经得起用户自己拿计算器验一遍。
  3. **跑出来是一份正常经营的诊断** —— 不是"赶紧关店"也不是"一票否决"。
     下面是实际跑 `engine.store_diagnosis.diagnose_existing_store` 的结果
     （探针 `_probe_sample_engine.py` 当时比了三组，A 组最像真实店）：

         月流水 135000 / 月租 15000 / 32㎡ / 杭州 / 3 人 / 前期投入 370000
         → 月成本合计 116239，月净利 18761，净利率 13.9%
         → 安全边际率 28.2%，租金余量 18760，外卖抽成占流水比 7.7%
         → 品牌对标：达蜜雪冰城公开基准（2024年前9个月，单店日均GMV×30=125532）的 108%

     ⚠️ 这组数**不是**拿引擎反推出来的"标准答案"，而是先按真实奶茶店的账挑的
     （蜜雪官方口径前期投入 37 万起，见 `agent/knowledge.py`），跑完引擎发现
     结论健康**才**留用。附录成本自查表也是照店主的记账习惯填的，与引擎拆解
     差约 2%（99300 vs 101239）—— 有这个差才像真的，完全对上反而假。

⚠️ 规格约束（改任何一处文字前先读这条）：
    · 说明块里**不许出现 U+3000**（全角空格）—— 那会被 `blank_span` 当成填写位。
    · 说明块里**不许出现品牌名 / 城市名 / 品类别名 / "自创"字样** ——
      抽取器是全文 `.search` 取首个命中，`extract_brand` 的"自创"分支更是
      **全文短路**（出现即判为无品牌，把用户真填的 蜜雪冰城 一起盖掉）。
    · 填写位宽度已由空白表定死（N ≤ 3 个全角空格），这里只做"填进去"，
      不动空白表本身。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
BLANK_MD = ROOT / 'docs' / '店铺经营月报-表单.md'
BLANK_HTML = ROOT / 'docs' / '店铺经营月报-表单.html'
SAMPLE_MD = ROOT / 'docs' / '店铺经营月报-样例.md'
SAMPLE_HTML = ROOT / 'docs' / '店铺经营月报-样例.html'

BLANK = '\u3000'          # 全角空格：填写位（与空白表、门禁同一口径）
SUMMARY_MARK = '；月流水'  # 第四章摘要行的识别标记

# ---------------------------------------------------------------- 样例数据
# (表单里的口径标签, 填进去的字面值, 抽取器应解出的值)
SAMPLE = [
    ('品类',         '奶茶',     '奶茶'),
    ('月流水',       '135000',   135000),
    ('月租金',       '15000',    15000),
    ('经营面积',     '32',       32),
    ('店铺所在城市', '杭州',     '杭州'),
    ('加盟品牌',     '蜜雪冰城', '蜜雪冰城'),
    ('全职员工',     '3',        3),
    ('前期投入',     '370000',   370000),
    ('每单金额',     '15',       15.0),
    ('日单量',       '300',      300),
]

# 附录「本月成本自查表」：照店主记账习惯填，合计 99300（不含租金）
# 与引擎当日拆解（月成本合计 116239 − 租金 15000 = 101239）差约 2% —— 故意留这个差
APPENDIX = [
    ('员工工资',       '18000'),
    ('物料采购',       '44000'),
    ('包装耗材',       '4200'),
    ('水电燃气',       '1700'),
    ('平台抽成',       '10400'),
    ('设备折旧与维修', '9500'),
    ('其他杂项',       '11500'),
    ('合计',           '99300'),
]

SAMPLE_HEADER_HTML = """<div class="warn">
  <p><strong>这是一份「填写样例」，不是空白表。</strong></p>
  <p>里面的数字全部是编出来的示例，用来演示每一栏该怎么填、填到多细。请把数字换成你自己的，或者改用另一份空白版《店铺经营月报》 —— 把示例数字照搬上传，只会换回一份跟你无关的诊断结论。</p>
  <p>下面正文里那句「本表一处示例数字都不印」说的是<strong>空白版</strong>；这份样例印出来的那组数，就是为了示范怎么填。</p>
</div>
"""

SAMPLE_HEADER_MD = """
> **这是一份「填写样例」，不是空白表。** 里面的数字全部是编出来的示例，用来演示每一栏该怎么填、填到多细。请把数字换成你自己的，或者改用另一份空白版《店铺经营月报》 —— 把示例数字照搬上传，只会换回一份跟你无关的诊断结论。
>
> 下面正文里那句「本表一处示例数字都不印」说的是**空白版**；这份样例印出来的那组数，就是为了示范怎么填。
"""


# ---------------------------------------------------------------- 填充原语
# ⚠️ 这三个函数是"什么算填写位"的**唯一实现**：verify_report_form.py 也从这里 import，
#    所以门禁验的就是生成器用的那套规则，不会各写一套而互相漂移。
def labeled_slots(text: str, labels, guard_line: bool = True):
    """找出文本里所有**未填的填写位**：返回 [(标签, 位置), …]（按出现顺序）。

    判定方式是"先找 U+3000 空白段、再回看它前面有没有口径标签"，而不是"标签之后
    找空白"：因为说明文字里也可能出现同名标签（如「月流水栏只填月口径」），
    那种地方**没有**空白段，不该被当成填写位。

    ⚠️ `guard_line` 必须开（默认）—— 必须限定"标签与空白在**同一行**"。
    否则会误判：摘要行填好之后（`…日单量300单。`），紧随其后的章节标题
    `第五章　口径说明与常见坑` 里的全角空格，其上文 12 字符内恰好有"日单量"，
    会被算成"日单量还有一个空着没填"。**只有实机复验时才会发现这种误报**，
    所以在判据里就把它掐掉。
    """
    out = []
    for m in re.finditer(r'\u3000+', text):
        line_start = text.rfind('\n', 0, m.start()) + 1 if guard_line else 0
        head = text[line_start:m.start()]
        for lb in labels:
            i = head.rfind(lb)
            if i != -1 and len(head[i + len(lb):]) <= 12:
                out.append((lb, m.start()))
                break
    return out


def blank_span(text: str, label: str, nth: int = 1):
    """找 label 之后第 nth 段 U+3000 空白（返回 (start, end)）；没有则 None。"""
    hits = [pos for lb, pos in labeled_slots(text, [label]) if lb == label]
    if len(hits) < nth:
        return None
    m = re.compile(r'\u3000+').match(text, hits[nth - 1])
    return m.span()


def fill(text: str, label: str, value: str, nth: int = 1, mode: str = 'head') -> str:
    """把 label 后的空白段替换成 value。

    mode='head' —— 用户顶格写（数字直接跟在标签后面）
    mode='tail' —— 用户写在空白段末尾（左边留着空格）—— 两种都必须能解出
    """
    span = blank_span(text, label, nth)
    if span is None:
        return text
    a, b = span
    ins = value if mode == 'head' else BLANK * (b - a) + value
    return text[:a] + ins + text[b:]


def fill_summary(text: str, values) -> str:
    """只填第四章那段摘要句（按句中空白的先后顺序灌值）。

    摘要句是"只复制一段话"那条路的唯一填写点；用 nth 逐字段定位很脆
    （句中与表内同名标签会互相串位），所以按整段替换。
    """
    lines = text.split('\n')
    for i, line in enumerate(lines):
        if SUMMARY_MARK not in line:
            continue
        it = iter(values)
        lines[i] = re.sub(r'\u3000+', lambda m: next(it, m.group(0)), line)
        break
    return '\n'.join(lines)


def fill_summary_html(html: str) -> str:
    """HTML 版摘要行：只动 `<div class="summary">` 里面的空白段。"""
    def rep(m):
        it = iter([v for _, v, _ in SAMPLE])
        return ('<div class="summary">'
                + re.sub(r'\u3000+', lambda mm: next(it, mm.group(0)), m.group(1))
                + '</div>')
    return re.sub(r'<div class="summary">(.*?)</div>', rep, html, flags=re.S)


def fill_table_cell(html: str, name: str, value: str) -> str:
    """填附录表格某一行的「本月金额」格。"""
    pat = r'(<tr><td>' + re.escape(name) + r'</td><td>)\u3000+(</td>)'
    return re.sub(pat, lambda m: m.group(1) + value + m.group(2), html, count=1)


# ---------------------------------------------------------------- 构造样例
def build_sample_html(blank_html: str) -> str:
    """空白 HTML → 填好样例 HTML。"""
    html = blank_html
    # 副标题标注"填写样例"，免得跟空白版混起来
    html = html.replace('<p class="sub">经营测算专家　·　输入表</p>',
                        '<p class="sub">经营测算专家　·　输入表　·　填写样例（示例数据）</p>')
    # 说明块插在副标题之后（在"这份表是干什么用的"之前）
    anchor = '<h2>这份表是干什么用的</h2>'
    html = html.replace(anchor, SAMPLE_HEADER_HTML + anchor, 1)
    # 十项：nth=1 → 第二章/第三章的表单栏（摘要行由 fill_summary_html 单独处理）
    for label, val, _ in SAMPLE:
        html = fill(html, label, val, nth=1)
    html = fill_summary_html(html)
    for name, val in APPENDIX:
        html = fill_table_cell(html, name, val)
    return html


def build_sample_md(blank_md: str) -> str:
    """空白 Markdown → 填好样例 Markdown（中间稿，交付面是 HTML）。"""
    md = blank_md
    md = md.replace('# 店铺经营月报\n',
                    '# 店铺经营月报（填写样例）\n' + SAMPLE_HEADER_MD + '\n', 1)
    for label, val, _ in SAMPLE:
        md = fill(md, label, val, nth=1)
    md = fill_summary(md, [v for _, v, _ in SAMPLE])
    for name, val in APPENDIX:
        pat = r'(\| ' + re.escape(name) + r' \| )\u3000+( \|)'
        md = re.sub(pat, lambda m: m.group(1) + val + m.group(2), md, count=1)
    return md


def render_markdown(md: str) -> str:
    """把 markdown 还原成 Word 里的可见文本（标记不产生字符）。"""
    out = []
    for line in md.splitlines():
        s = line.replace('**', '')
        s = re.sub(r'^\s{0,3}#{1,6}\s*', '', s)
        s = re.sub(r'^\s{0,3}>\s?', '', s)
        s = re.sub(r'^\s{0,3}[-*]\s+', '', s)
        out.append(s)
    return '\n'.join(out)


def html_text(html: str) -> str:
    """粗抽 HTML 可见文本（行内格式抹掉、块级标签换行）—— 见门禁 §5 说明。

    ⚠️ 表格要按**真实 docx dump 的样子**来拼：`live_report_probe.dump()` 对表格行
    用的是 `' | '.join(cell.text)`，所以一行三格在抽取面上是**同一行**。
    如果这里图省事把每个 `<td>` 都换成换行，附录表的"员工工资"与它的金额格
    就会分处两行 —— 那会让"填写位对不上账"这类判据出现假阳性
    （标签与空白不在同一行 = 看起来没填），正是本项目反复踩的那种坑。
    """
    from html import unescape as _unescape
    t = re.sub(r'(?is)<head.*?</head>', ' ', html)
    t = re.sub(r'(?is)<style.*?</style>', ' ', t)
    t = re.sub(r'(?s)<!--.*?-->', ' ', t)
    t = re.sub(r'(?is)</?(?:strong|b|em|i|span|font|u|sub|sup|a)\b[^>]*>', '', t)
    # 表格：<tr> 起新行、</td> 与 </th> 作 ' | '（与 docx dump 的表格行同构）
    t = re.sub(r'(?is)<tr[^>]*>', '\n', t)
    t = re.sub(r'(?is)</tr\s*>', '', t)
    t = re.sub(r'(?is)</t[dh]\s*>', ' | ', t)
    t = re.sub(r'(?is)<t[dh][^>]*>', '', t)
    t = re.sub(r'(?s)<[^>]+>', '\n', t)
    t = _unescape(t)
    t = re.sub(r'[ \t]+', ' ', t)
    t = re.sub(r'(?m)[ ]+\|', ' |', t)
    t = re.sub(r'\n\s*\n+', '\n', t)
    return t.strip()


if __name__ == '__main__':
    # 直接跑 = 只在内存里构造一遍，确认没崩（真正落盘走 make_sample_report.py）
    md = build_sample_md(BLANK_MD.read_text(encoding='utf-8'))
    ht = build_sample_html(BLANK_HTML.read_text(encoding='utf-8'))
    print(f'md  {len(md)} 字符 / html {len(ht)} 字符')
