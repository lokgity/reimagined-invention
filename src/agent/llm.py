# -*- coding: utf-8 -*-
"""
llm.py —— 统一 LLM 调用（支持降级：火山方舟 doubao-seed-2.1-pro → turbo
          → 小米 mimo → DeepSeek → 规则解读）
=====================================================================
"""
import json
import sys
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
    'DeepSeek-V4-Flash': (LLM_ARK_API_KEY, LLM_ARK_BASE_URL, 'DeepSeek-V4-Flash', {'max_tokens': 1600}),
    'mimo-v2.5': None,  # 未配置，选择时回退到默认链
}

DEFAULT_MODEL = 'Doubao-Seed-2.1-turbo'


def set_llm_model(name):
    """设置当前会话使用的模型（应用在每个 on_message 前调用一次）。"""
    _MODEL_CTX.set(name)


def current_model_name():
    """当前会话选中的模型显示名；未选/未配置返回默认名。"""
    name = _MODEL_CTX.get()
    return name if name in MODEL_OPTIONS else DEFAULT_MODEL


def _call_llm(api_key, base_url, model, system_msg, user_msg, temperature=0.3, timeout=120, extra=None):
    """通用 LLM 调用函数
    extra: 额外请求体字段(如 max_tokens / thinking)，火山方舟用。
    """
    import urllib.request
    import urllib.error
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system_msg},
            {'role': 'user', 'content': user_msg},
        ],
        'temperature': temperature,
    }
    if extra:
        payload.update(extra)
    req = urllib.request.Request(
        f'{base_url.rstrip("/")}/chat/completions',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json',
                 'Authorization': f'Bearer {api_key}'},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return data['choices'][0]['message']['content']
    except urllib.error.HTTPError as e:
        body = ''
        try:
            body = e.read().decode('utf-8', 'replace')[:200]
        except Exception:
            pass
        raise Exception(f'HTTP {e.code} {body}') from e


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


async def call_llm(system_msg: str, user_msg: str, temperature=0.3, timeout=120) -> str:
    """异步 LLM 调用，四级降级：火山方舟pro → 火山方舟turbo → mimo → DeepSeek → 抛异常"""
    import asyncio

    def _sync_call():
        providers = _provider_list()
        errors = []
        for key, url, model, name, extra in providers:
            try:
                return _call_llm(key, url, model, system_msg, user_msg, temperature, timeout, extra)
            except Exception as e:
                errors.append(f'{name}: {e}')
        raise Exception('所有 LLM 调用失败：' + ('；'.join(errors) if errors else '未配置任何 API KEY'))

    return await asyncio.to_thread(_sync_call)


def call_llm_sync(system_msg: str, user_msg: str, temperature=0.3, timeout=120) -> str:
    """同步版本（用于不需要 async 的场景）"""
    providers = _provider_list()
    errors = []
    for key, url, model, name, extra in providers:
        try:
            return _call_llm(key, url, model, system_msg, user_msg, temperature, timeout, extra)
        except Exception as e:
            errors.append(f'{name}: {e}')
    raise Exception('所有 LLM 调用失败：' + ('；'.join(errors) if errors else '未配置任何 API KEY'))
