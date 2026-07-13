"""AI Consensus — dual-model filing evaluation with analyst + verifier pattern.

Analyst: Claude Haiku 4.5 (Anthropic SDK). Verifier: DeepSeek V4 Flash (OpenAI SDK).
"""

import json
import os
import time
from pathlib import Path

from anthropic import Anthropic
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv(override=True)

from utils.json_extract import extract_json

HAIKU_MODEL = "claude-haiku-4-5-20251001"
DEEPSEEK_MODEL = "deepseek-v4-flash"

# deepseek-v4-flash defaults to thinking mode and on Tier-2F-sized prompts burns
# the whole completion budget on reasoning_content, returning content="" with
# finish_reason="length" (17/21 verifier calls starved Jul 7-10 -- report
# 2026-07-12 N-1). Disable thinking on every DeepSeek call, mirroring the Haiku
# analyst's thinking={"type": "disabled"} below; keep a raised max_tokens as the
# second belt so a silently-dropped param degrades to slow-but-alive instead of
# re-starving (worst observed reasoning burn: 1,146 tokens).
DEEPSEEK_MAX_TOKENS = 2500
DEEPSEEK_NO_THINKING = {"thinking": {"type": "disabled"}}

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()

haiku_client = Anthropic(api_key=ANTHROPIC_API_KEY)
deepseek_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
ANALYST_PROMPT = (_PROMPTS_DIR / "ai_consensus_analyst.txt").read_text(encoding="utf-8")
VERIFIER_PROMPT = (_PROMPTS_DIR / "ai_consensus_verifier.txt").read_text(encoding="utf-8")


def _retry_json(call_fn, label="model", max_retries=2):
    """Call `call_fn()` -> raw text, clean + parse JSON, retry on failure.

    `call_fn` is a zero-arg closure that invokes the SDK and returns the raw
    text from the response. This keeps the retry logic SDK-agnostic — the
    closure handles Anthropic vs OpenAI response path differences.
    """
    last_error = None

    for attempt in range(max_retries + 1):
        raw = call_fn()

        if not isinstance(raw, str) or not raw.strip():
            if attempt < max_retries:
                print(f"  [WARN] {label} attempt {attempt+1}: empty response, retrying...")
                time.sleep(2)
                continue
            raise ValueError(f"{label}: empty response after {max_retries+1} attempts")

        try:
            return extract_json(raw)
        except json.JSONDecodeError as e:
            last_error = e
            if attempt < max_retries:
                print(f"  [WARN] {label} attempt {attempt+1}: JSON parse failed ({e}), retrying...")
                time.sleep(2)
                continue
            raise ValueError(
                f"{label}: JSON parse failed after {max_retries+1} attempts: {e}"
            ) from e

    raise last_error


def run_analyst(context, prompt_template: str | None = None):
    """Call Haiku analyst. Returns parsed dict with tradeable, directional_bias, etc."""

    template = prompt_template if prompt_template is not None else ANALYST_PROMPT

    def _call():
        response = haiku_client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=600,
            temperature=0.3,
            thinking={"type": "disabled"},
            messages=[{"role": "user", "content": template.format(context=context)}],
        )
        # Anthropic SDK can return multiple content blocks (ThinkingBlock + TextBlock
        # when extended thinking is enabled). Find the first TextBlock with non-empty text.
        for block in response.content:
            if hasattr(block, 'text') and block.text:
                return block.text
        return ""

    return _retry_json(_call, label="analyst")


def run_verifier(context, analyst_output, prompt_template: str | None = None):
    """Call DeepSeek verifier. Returns parsed dict with verdict, agreement_score, etc."""

    template = prompt_template if prompt_template is not None else VERIFIER_PROMPT

    def _call():
        response = deepseek_client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            max_tokens=DEEPSEEK_MAX_TOKENS,
            temperature=0.3,
            extra_body=DEEPSEEK_NO_THINKING,
            messages=[{"role": "user", "content": template.format(
                context=context, analyst_output=json.dumps(analyst_output)
            )}],
        )
        if response.choices and response.choices[0].message.content:
            return response.choices[0].message.content
        return ""

    return _retry_json(_call, label="verifier")


def _run_deepseek_as_analyst(context, prompt_template=None):
    """Solo fallback: route the analyst prompt through DeepSeek when Anthropic is down."""
    template = prompt_template if prompt_template is not None else ANALYST_PROMPT

    def _call():
        response = deepseek_client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            max_tokens=DEEPSEEK_MAX_TOKENS,
            temperature=0.3,
            extra_body=DEEPSEEK_NO_THINKING,
            messages=[{"role": "user", "content": template.format(context=context)}],
        )
        if response.choices and response.choices[0].message.content:
            return response.choices[0].message.content
        return ""

    return _retry_json(_call, label="solo-deepseek")


def _safe_conf(d, key):
    """Read an integer confidence field; return None if missing or not a number."""
    v = d.get(key)
    if isinstance(v, (int, float)):
        return v
    return None


def determine_consensus(haiku, flash):
    """Two-model decision logic (§7.3). Returns (decision, reason)."""
    if not haiku.get("tradeable"):
        return ("SKIP", "Analyst says not tradeable")

    if flash.get("verdict") == "CHALLENGE" and flash.get("agreement_score", 0) < 70:
        return ("SKIP", f"Verifier challenged ({flash['agreement_score']})")

    if haiku["directional_bias"] != flash["my_directional_bias"]:
        return ("SKIP", "Direction mismatch")

    haiku_conf = _safe_conf(haiku, "confidence")
    flash_conf = _safe_conf(flash, "my_confidence")
    if haiku_conf is None or flash_conf is None:
        return ("SKIP", "Missing or invalid confidence field")

    avg_conf = (haiku_conf + flash_conf) / 2
    if avg_conf < 65:
        return ("SKIP", f"Avg confidence {avg_conf} < 65")

    return ("PROCEED", "Consensus reached")
