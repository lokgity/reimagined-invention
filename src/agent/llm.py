# -*- coding: utf-8 -*-
"""
llm.py —— 统一 LLM 调用（支持降级：火山方舟 doubao-seed-2.1-pro → turbo
          → 小米 mimo → DeepSeek → 规则解读）
=====================================================================
"""
import json
import sys
import time
import contextvars
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    LLM_ARK_API_KEY, LLM_ARK_BASE_URL, LLM_ARK_MODEL, LLM_ARK_MODEL_FALLBACK,
    LLM_API_KEY, LLM_BASE_URL, LLM_MODEL,
    LLM_FALLBACK_API_KEY, LLM_FALLBACK_BASE_URL, LLM_FALLBACK_MODEL,
)

# 用户可切换的模型选择（会话级，通过 contextvar 隔离，不跨会话串扰）
_MODEL_CTX = contextvars.ContextVar('llm_model', default=None)

# 可选模型 -> (api_key, base_url, model_id, extra)；None 表示未真实配置
# 三个模型共用同一把火山方舟 key（用户提供）；mimo-v2.5 暂未真实配置
_ARK_EXTRA = {'max_tokens': 1600, 'thinking': {'type': 'disabled'}}
MODEL_OPTIONS = {
    'Doubao-Seed-2.1-turbo': (LLM_ARK_API_KEY, LLM_ARK_BASE_URL, 'doubao-seed-2-1-turbo-260628', _ARK_EXTRA),
    # ⚠️ 修复 2026-09-15：原先这一项**漏了 thinking disabled**（豆包 pro 有）。
    #    DeepSeek 系列在方舟上默认开启深度思考，输出极长，
    #    实测界面「等待模型响应」8 分钟不返回，最终超时。
    #    与豆包 pro 同理，必须关掉思考模式。
    'DeepSeek-V4-Flash': (LLM_ARK_API_KEY, LLM_ARK_BASE_URL, 'DeepSeek-V4-Flash',
                          {'max_tokens': 1600, 'thinking': {'type': 'disabled'}}),
    'mimo-v2.5': None,  # 未配置，选择时回退到默认链
}

DEFAULT_MODEL = 'Doubao-Seed-2.1-turbo'

# 降级链的**总超时预算**（秒）。
# ⚠️ 背景：降级链是串行的（已选 → 豆包pro → 豆包turbo → mimo → DeepSeek），
#    每个 provider 各自 timeout=120s → 最坏 5×120s = 10 分钟。
#    期间 UI 只是转圈、零反馈，用户以为程序挂了（实测卡 8 分钟）。
#    加上总预算后，最坏总耗时被限制在 DEFAULT_TOTAL_BUDGET 秒内。
DEFAULT_TOTAL_BUDGET = 180.0

# 降级回调（同步）：切换 provider 前触发，供上层把"正在换模型重试"
# 写进前端可折叠的「执行过程」面板，避免用户干等。
_RETRY_CTX = contextvars.ContextVar('llm_retry_cb', default=None)


def set_retry_callback(cb):
    """注册降级回调（同步函数，接收一行提示文本）。"""
    _RETRY_CTX.set(cb)


def _notify_retry(msg: str):
    cb = _RETRY_CTX.get()
    if cb:
        try:
            cb(msg)
        except Exception:
            pass


def set_llm_model(name):
    """设置当前会话使用的模型（应用在每个 on_message 前调用一次）。"""
    _MODEL_CTX.set(name)


def current_model_name():
    """当前会话选中的模型显示名；未选/未配置返回默认名。"""
    name = _MODEL_CTX.get()
    return name if name in MODEL_OPTIONS else DEFAULT_MODEL


def _post_messages(api_key, base_url, model, messages, temperature, timeout,
                   extra=None, tools=None):
    """发一次 /chat/completions，返回 **choices[0].message 整个对象**
    （含 `content` 与可能存在的 `tool_calls`）。

    ⚠️ 与 `_call_llm` 的区别：后者只取 content，会把 tool_calls 丢掉。
    真 function calling 必须拿到完整 message 才能继续回合。
    """
    import urllib.request
    import urllib.error
    payload = {'model': model, 'messages': messages, 'temperature': temperature}
    if extra:
        payload.update(extra)
    if tools:
        payload['tools'] = tools
        payload.setdefault('tool_choice', 'auto')
    req = urllib.request.Request(
        f'{base_url.rstrip("/")}/chat/completions',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json',
                 'Authorization': f'Bearer {api_key}'},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return data['choices'][0]['message']
    except urllib.error.HTTPError as e:
        body = ''
        try:
            body = e.read().decode('utf-8', 'replace')[:300]
        except Exception:
            pass
        raise Exception(f'HTTP {e.code} {body}') from e


def _call_llm(api_key, base_url, model, system_msg, user_msg, temperature=0.3, timeout=120, extra=None):
    """通用 LLM 调用函数
    extra: 额外请求体字段(如 max_tokens / thinking)，火山方舟用。
    """
    msg = _post_messages(api_key, base_url, model,
                         [{'role': 'system', 'content': system_msg},
                          {'role': 'user', 'content': user_msg}],
                         temperature, timeout, extra)
    return msg.get('content') or ''



def _provider_list():
    """按优先级返回 [(api_key, base_url, model, 名称, extra), ...]
    先尝试用户当前选择的模型；再走默认降级链（豆包pro→turbo→mimo→DeepSeek）。
    火山方舟豆包：关掉思考模式(thinking disabled) + 限制 max_tokens，否则
    doubao-seed-2.1-pro 默认深度思考会远超 40s 超时（实测 60s+ 不返回）。
    """
    providers = []
    chosen = _MODEL_CTX.get()
    if chosen and MODEL_OPTIONS.get(chosen):
        key, url, model, extra = MODEL_OPTIONS[chosen]
        providers.append((key, url, model, f'已选·{chosen}', extra))
    if LLM_ARK_API_KEY:
        providers.append((LLM_ARK_API_KEY, LLM_ARK_BASE_URL, LLM_ARK_MODEL,
                          f'火山方舟·{LLM_ARK_MODEL}', _ARK_EXTRA))
        providers.append((LLM_ARK_API_KEY, LLM_ARK_BASE_URL, LLM_ARK_MODEL_FALLBACK,
                          f'火山方舟·{LLM_ARK_MODEL_FALLBACK}', _ARK_EXTRA))
    if LLM_API_KEY:
        providers.append((LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, f'小米mimo·{LLM_MODEL}', None))
    if LLM_FALLBACK_API_KEY:
        providers.append((LLM_FALLBACK_API_KEY, LLM_FALLBACK_BASE_URL, LLM_FALLBACK_MODEL,
                          f'DeepSeek·{LLM_FALLBACK_MODEL}', None))
    return providers


async def call_llm(system_msg: str, user_msg: str, temperature=0.3, timeout=120,
                   total_budget: float = DEFAULT_TOTAL_BUDGET) -> str:
    """异步 LLM 调用，四级降级：火山方舟pro → 火山方舟turbo → mimo → DeepSeek → 抛异常

    total_budget：整条降级链的**总耗时上限**（秒）。超过即停止重试并抛异常，
    避免界面无反馈地干转十几分钟。
    """
    import asyncio

    def _sync_call():
        providers = _provider_list()
        errors = []
        t0 = time.time()
        for idx, (key, url, model, name, extra) in enumerate(providers):
            remain = total_budget - (time.time() - t0)
            if remain <= 5:
                errors.append(f'{name}: 跳过（已达总超时预算 {total_budget:.0f}s）')
                continue
            if idx > 0:
                _notify_retry(f'切换到备用模型：{name}（第 {idx + 1} 个，'
                              f'已用 {time.time() - t0:.0f}s，剩余预算 {remain:.0f}s）')
            try:
                return _call_llm(key, url, model, system_msg, user_msg, temperature,
                                 min(timeout, remain), extra)
            except Exception as e:
                errors.append(f'{name}: {e}')
        raise Exception('所有 LLM 调用失败：' + ('；'.join(errors) if errors else '未配置任何 API KEY'))

    return await asyncio.to_thread(_sync_call)


def call_llm_sync(system_msg: str, user_msg: str, temperature=0.3, timeout=120,
                  total_budget: float = DEFAULT_TOTAL_BUDGET) -> str:
    """同步版本（用于不需要 async 的场景）"""
    providers = _provider_list()
    errors = []
    t0 = time.time()
    for idx, (key, url, model, name, extra) in enumerate(providers):
        remain = total_budget - (time.time() - t0)
        if remain <= 5:
            errors.append(f'{name}: 跳过（已达总超时预算 {total_budget:.0f}s）')
            continue
        if idx > 0:
            # 与 call_llm(异步版) 保持一致的文案：带上已用时长与剩余预算，
            # 否则 UI 的「执行过程」面板只说"正在切换"，用户不知道还要等多久。
            _notify_retry(f'切换到备用模型：{name}（第 {idx + 1} 个，'
                          f'已用 {time.time() - t0:.0f}s，剩余预算 {remain:.0f}s）')
        try:
            return _call_llm(key, url, model, system_msg, user_msg, temperature,
                             min(timeout, remain), extra)
        except Exception as e:
            errors.append(f'{name}: {e}')
    raise Exception('所有 LLM 调用失败：' + ('；'.join(errors) if errors else '未配置任何 API KEY'))


# ---------------------------------------------------------------
# 真 function calling（2026-09-16，§6）
# ---------------------------------------------------------------
# 为什么需要它：专家 frontmatter 声明的 `tools`/`forbids` 白名单原本**无人执行**
# —— `call_llm()` 签名里没有 tools 参数，模型既不知道有什么工具，也没有
# "调用被拒"这回事。于是"专家 vs 裸 LLM"在运行时几乎是同一回事。
#
# 本函数把白名单变成**真的执行边界**：模型只能看到白名单内的工具；
# 若它调用白名单外的工具，`tool_runner` 会返回明确的拒绝说明并回灌给模型。
#
# 两条工程纪律：
# 1. **严格增量**：若某 provider 不支持 tools 参数（返回 4xx/参数错误），
#    本函数会自动**降级为不带 tools 的普通调用**，绝不因此让对话失败
#    —— 否则"接 function calling"反而成了一处新的单点故障。
# 2. **有界**：`max_rounds` 限制工具往返轮数，避免模型无限调工具把
#    界面拖死（与 LLM 链总预算同理）。
async def call_llm_with_tools(system_msg: str, user_msg: str, tools=None,
                              tool_runner=None, max_rounds: int = 3,
                              temperature=0.3, timeout=120,
                              total_budget: float = DEFAULT_TOTAL_BUDGET):
    """带工具调用的 LLM 回合。返回 `(文本, trace)`。

    trace: [{'round','tool','args','ok','denied','note'}, ...]，
    供「执行过程」面板展示"这位专家实际调了什么、被拒了什么"。
    """
    import asyncio

    def _loop(use_tools: bool):
        providers = _provider_list()
        errors = []
        trace = []
        t0 = time.time()
        for idx, (key, url, model, name, extra) in enumerate(providers):
            remain = total_budget - (time.time() - t0)
            if remain <= 5:
                errors.append(f'{name}: 跳过（已达总超时预算 {total_budget:.0f}s）')
                continue
            if idx > 0:
                _notify_retry(f'切换到备用模型：{name}（第 {idx + 1} 个，'
                              f'已用 {time.time() - t0:.0f}s，剩余预算 {remain:.0f}s）')
            msgs = [{'role': 'system', 'content': system_msg},
                    {'role': 'user', 'content': user_msg}]
            _t = []
            try:
                for rnd in range(max_rounds):
                    msg = _post_messages(key, url, model, msgs, temperature,
                                         min(timeout, remain), extra,
                                         tools if use_tools else None)
                    tcs = msg.get('tool_calls') or []
                    if not tcs:
                        return (msg.get('content') or ''), _t
                    msgs.append({'role': 'assistant',
                                 'content': msg.get('content') or '',
                                 'tool_calls': tcs})
                    for tc in tcs:
                        fn = tc.get('function') or {}
                        _nm, _arg = fn.get('name'), fn.get('arguments')
                        try:
                            res = (tool_runner(_nm, _arg) if tool_runner
                                   else {'ok': False, 'error': '未注册工具执行器'})
                        except Exception as e:            # 执行器自身异常也要回灌
                            res = {'ok': False, 'error': f'执行器异常：{e}'}
                        _t.append({'round': rnd + 1, 'tool': _nm, 'args': _arg,
                                   'ok': bool(res.get('ok')),
                                   'denied': bool(res.get('denied')),
                                   'note': (res.get('error') or '')[:200]})
                        msgs.append({'role': 'tool',
                                     'tool_call_id': tc.get('id') or (_nm or 'tool'),
                                     'content': json.dumps(res, ensure_ascii=False,
                                                           default=str)})
                # 轮数用尽 → 收口：明确要求它立刻给答案，不再调工具
                msgs.append({'role': 'user',
                             'content': '（已达到工具调用轮数上限，请立刻基于已有信息'
                                        '给出最终回答，不要再调用工具。）'})
                msg = _post_messages(key, url, model, msgs, temperature,
                                     min(timeout, remain), extra, None)
                return (msg.get('content') or ''), _t
            except Exception as e:
                errors.append(f'{name}: {e}')
                trace = trace or _t
        raise Exception('所有 LLM 调用失败：' + ('；'.join(errors) if errors else '未配置任何 API KEY'))

    def _sync():
        try:
            return _loop(use_tools=bool(tools))
        except Exception:
            if not tools:
                raise
            # 降级：provider 可能不支持 tools → 退回普通调用（严格增量，不新增故障点）
            text, trace = _loop(use_tools=False)
            trace = trace + [{'round': 0, 'tool': '(降级)', 'args': None,
                              'ok': True, 'denied': False,
                              'note': '当前模型未接受 tool 参数，已降级为普通对话'}]
            return text, trace

    return await asyncio.to_thread(_sync)

