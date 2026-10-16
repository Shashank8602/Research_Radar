"""LiteLLM setup: Groq primary, fallbacks from config, validated structured output."""

from __future__ import annotations

import json
from typing import TypeVar

from litellm import Router
from pydantic import BaseModel, ValidationError

from radar import tracing
from radar.config import AppConfig, Env, get_env, load_config

T = TypeVar("T", bound=BaseModel)

_KEY_FOR_PROVIDER = {
    "groq": "groq_api_key",
    "gemini": "gemini_api_key",
    "openrouter": "openrouter_api_key",
}


def _api_key(model: str, env: Env) -> str | None:
    return getattr(env, _KEY_FOR_PROVIDER.get(model.split("/", 1)[0], ""), None)


def build_router(config: AppConfig | None = None, env: Env | None = None) -> Router:
    config = config or load_config()
    env = env or get_env()
    chain = [config.models.judge, *config.models.fallbacks]
    model_list = []
    for i, model in enumerate(chain):
        params = {"model": model}
        key = _api_key(model, env)
        if key:
            params["api_key"] = key
        name = "judge" if i == 0 else f"judge-fb{i}"
        model_list.append({"model_name": name, "litellm_params": params})
    fallbacks = [{"judge": [m["model_name"] for m in model_list[1:]]}] if len(chain) > 1 else []
    return Router(model_list=model_list, fallbacks=fallbacks, num_retries=2, retry_after=5)


_SCHEMA_INSTRUCTION = (
    "Respond with a single JSON object that conforms to this JSON Schema. "
    "Output JSON only, no prose or code fences.\n\nSchema:\n{schema}"
)


def complete_structured(
    prompt: str,
    schema: type[T],
    *,
    system: str | None = None,
    name: str = "structured-completion",
    router: Router | None = None,
    max_validation_retries: int = 1,
) -> tuple[T, str]:
    """Call the LLM and return (validated object, model id actually used).

    Provider-agnostic: asks for JSON mode, embeds the schema in the prompt and validates with
    Pydantic, re-asking once with the validation error. Works across Groq/Gemini/OpenRouter
    regardless of their native json_schema support."""
    router = router or build_router()
    requested = router.model_list[0]["litellm_params"]["model"]
    schema_text = json.dumps(schema.model_json_schema())
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "system", "content": _SCHEMA_INSTRUCTION.format(schema=schema_text)})
    messages.append({"role": "user", "content": prompt})

    last_error: Exception | None = None
    for _ in range(max_validation_retries + 1):
        with tracing.generation(
            name, model=requested, input=list(messages), model_parameters={"temperature": 0}
        ) as gen:
            resp = router.completion(
                model="judge",
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0,
            )
            content = resp.choices[0].message.content or ""
            if gen is not None:
                _record_generation(gen, resp, content)
        try:
            return schema.model_validate_json(content), resp.model or ""
        except ValidationError as e:
            last_error = e
            messages.append({"role": "assistant", "content": content})
            retry = f"That did not validate: {e}. Return corrected JSON only."
            messages.append({"role": "user", "content": retry})
    raise ValueError(f"LLM output failed validation after retries: {last_error}")


def _record_generation(gen, resp, content: str) -> None:
    """Attach actual model, token usage and reasoning (if any) to a generation."""
    usage = getattr(resp, "usage", None)
    msg = resp.choices[0].message
    reasoning = getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None)
    gen.update(
        model=resp.model or None,
        output=[{"role": "assistant", "content": content}],
        usage_details=(
            {
                "input": usage.prompt_tokens,
                "output": usage.completion_tokens,
                "total": usage.total_tokens,
            }
            if usage
            else None
        ),
        metadata={"reasoning": reasoning[:2000]} if reasoning else None,
    )
