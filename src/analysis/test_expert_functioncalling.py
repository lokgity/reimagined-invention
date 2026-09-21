# -*- coding: utf-8 -*-
"""test_expert_functioncalling.py —— 专家 function calling 真实链路（网络信息性）
==========================================================================
⚠️ **本套件依赖外网 LLM**，天然不确定，按项目纪律**不进离线门禁**，
   只作信息性验证（与 test_vision_storefront / test_composite_intent 同类）。

它要回答的问题是 §6 的核心质疑：
    "我点这些专家，跟我直接把问题丢给大模型，实质上有区别吗？"

三条断言（前两条是硬断言，第三条是信息性）：
  1. **工具真的被调用**且执行成功：trace 里出现一次 `ok=True` 的工具调用。
  2. **回答引用了系统独有数据**：模型原样复述了工具返回的数值
     （这些值来自本仓库的品牌表/标定，裸 LLM 无从知道）。
  3. **裸 LLM 对照组**：同一问题、无工具 → trace 必为空。
     至于它会不会**蒙对**那个数值，只作 INFO 记录（模型可能恰好猜中量级，
     不断言 —— 项目纪律：不对 LLM 自由文本锁定措辞）。

用法：C:\\Python314\\python.exe src/analysis/test_expert_functioncalling.py
输出：同目录 _expert_fc.txt
"""
import io
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / '.pylibs'))

OUT = HERE / '_expert_fc.txt'
L, FAIL, INFO = [], [], []


def p(*a):
    s = ' '.join(str(x) for x in a)
    print(s)
    L.append(s)


def check(name, cond, detail=''):
    p(f'  {"PASS" if cond else "FAIL"}  {name}' + (f'  |  {detail}' if detail else ''))
    if not cond:
        FAIL.append(name)


def info(name, detail=''):
    p(f'  ---- {name}' + (f'  |  {detail}' if detail else ''))
    INFO.append(name)


async def main():
    import json
    import asyncio
    from experts import toolbox as TB
    from agent.llm import call_llm, call_llm_with_tools

    EXPERT = 'franchise_advisor'
    tools = TB.tool_schemas(EXPERT)
    p(f'专家 {EXPERT} 暴露工具 {len(tools)} 个：'
      f'{[t["function"]["name"] for t in tools]}')

    # 取一个**系统独有**的数值：UPLIFT 是本仓库用 9 品牌同商圈口径标定的，
    # 裸 LLM 不可能知道这个精确值。
    from engine.brands import brand_uplift
    _bn, truth = brand_uplift('蜜雪冰城')      # ⚠️ 返回元组 (品牌名, 系数)
    p(f'系统内「蜜雪冰城」同商圈溢价系数 = {truth}（本仓库标定值，裸 LLM 无从知道）')

    Q = ('请调用 brand_uplift 工具，查询品牌「蜜雪冰城」的同商圈溢价系数，'
         '然后把工具返回的系数原样告诉我（给到小数第 3 位）。'
         '如果工具返回失败，就直说拿不到，不要编。')

    # ---- ① 带工具：专家路径 ----
    try:
        txt, trace = await call_llm_with_tools(
            '你是加盟顾问，必须用工具取数，不许凭记忆回答。', Q,
            tools=tools, tool_runner=lambda n, a: TB.run_tool(EXPERT, n, a),
            max_rounds=3, temperature=0.2, timeout=90)
    except Exception as e:
        check('专家路径调用成功（LLM 可达）', False, f'{type(e).__name__}: {e}')
        txt, trace = '', []

    p('')
    p('  [专家路径] trace =')
    for t in trace:
        p(f'    round{t.get("round")} {t.get("tool")} ok={t.get("ok")} '
          f'denied={t.get("denied")} {t.get("note") or ""}')
    p(f'  [专家路径] 回答前 200 字：{(txt or "")[:200]}')

    _real = [t for t in trace if t.get('ok') and t.get('tool') != '(降级)']
    check('工具**真的被调用**且执行成功（trace 里有 ok=True 的调用）',
          bool(_real), str([t.get('tool') for t in trace]))
    check('工具白名单被尊重：没有出现白名单外的工具',
          all(t['tool'] in TB.allowed_tools(EXPERT) or t['tool'] == '(降级)'
              for t in trace),
          str([t['tool'] for t in trace]))
    if truth is not None:
        _s = f'{truth:.3f}'
        check('回答引用了**系统独有**的数值（原样复述工具返回值）',
              _s in (txt or '') or str(truth) in (txt or ''),
              f'期望出现 {_s}')
    if any(t.get('tool') == '(降级)' for t in trace):
        info('当前模型未接受 tool 参数，已按设计降级为普通对话（不影响可用性）')

    # ---- ② 无工具：裸 LLM 对照组 ----
    try:
        bare = await call_llm('你是一位顾问，请直接回答。', Q,
                              temperature=0.2, timeout=90)
    except Exception as e:
        bare = ''
        info(f'对照组调用失败：{e}')
    p('')
    p(f'  [裸 LLM 对照] 回答前 200 字：{(bare or "")[:200]}')
    _s = f'{truth:.3f}' if truth is not None else None
    if _s:
        info('裸 LLM 是否**恰好**说出同一个精确值（不做断言，模型可能蒙对量级）',
             f'{"出现" if _s in (bare or "") else "未出现"} {_s}')
    info('对照组无 trace 是结构性事实（未传 tools → 不可能有工具调用）',
         'call_llm 只返回文本，无 trace 通道')

    p('')
    p('=' * 60)
    if FAIL:
        p(f'FAILED = {len(FAIL)}：' + ' / '.join(FAIL))
    else:
        p('全部 PASS')
    p(f'（信息性记录 {len(INFO)} 条）')


if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    try:
        asyncio_run = __import__('asyncio').run
        asyncio_run(main())
    except Exception as e:
        p(f'💥 未捕获异常：{type(e).__name__}: {e}')
        FAIL.append('未捕获异常')
    OUT.write_text('\n'.join(L), encoding='utf-8')
    print(f'\n[写入] {OUT}')
    sys.exit(1 if FAIL else 0)
