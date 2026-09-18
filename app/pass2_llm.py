"""Pass 2: semantic detection via a local LLM behind an OpenAI-compatible API
(LM Studio or Unsloth Studio, run on the HOST — never inside the container).

Rules encoded here (from the design):
- The LLM DETECTS only; it never rewrites text. It returns strict JSON:
  [{quote, category, confidence, reason}] and the caller maps quotes back to
  character offsets deterministically.
- A quote maps to a span ONLY if found verbatim inside the chunk it came
  from (chunks are exact slices of the plain text, so chunk index + chunk
  offset = absolute offset). Everything else is surfaced as "unverified"
  for the human review queue, never auto-replaced.
- Trust tier: LLM confidence is scaled to at most 0.80, under the 0.85
  review threshold — regex and NER always win overlaps.

Config via environment variables (all optional):
- OBFUSCATOR_LLM_ENABLED   (default "1")
- OBFUSCATOR_LLM_BASE_URL  (default "http://127.0.0.1:8888/v1")
- OBFUSCATOR_LLM_API_KEY   (default "lmstudio" — used as Bearer; local servers ignore it)
- OBFUSCATOR_LLM_MODEL     (default: first model listed by the server)
- OBFUSCATOR_LLM_TIMEOUT   (default "180")
"""
import json
import os
import re
from pathlib import Path

import httpx

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _load_env_file() -> None:
    """Tiny .env loader: project-root .env, KEY=VALUE lines, no comments.
    Existing process environment always wins."""
    if not _ENV_FILE.is_file():
        return
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file()

PROMPT_SYSTEM = (
    "You are a data-protection scanner. You find sensitive or identifying "
    "content in TEXT the user gives you. You never rewrite text. You reply "
    "ONLY with a JSON array, no prose, no code fences. Each element is an "
    'object: {"quote": <exact verbatim span from the text>, "category": one '
    'of ["person","org","place","free_text"], "confidence": <0.00-1.00>, '
    '"reason": <short justification>}. '
    "Include anything a human would consider identifying, confidential, or "
    "business-sensitive: people, orgs, addresses, product codenames, contract "
    "terms, unreleased features, internal project names. Do NOT include "
    "generic words, dates, or common terms. If nothing qualifies, reply []."
)

_CATEGORIES = {"person", "org", "place", "free_text"}
_CHUNK_CHARS = 2400
_CHUNK_OVERLAP = 240
_TRUST_CAP = 0.80


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def llm_enabled() -> bool:
    return _env("OBFUSCATOR_LLM_ENABLED", "1") == "1"


def base_url() -> str:
    return _env("OBFUSCATOR_LLM_BASE_URL", "http://127.0.0.1:8888/v1").rstrip("/")


def _headers() -> dict:
    key = _env("OBFUSCATOR_LLM_API_KEY", "lmstudio")
    return {"Authorization": f"Bearer {key}"}


def _timeout() -> tuple:
    return (float(_env("OBFUSCATOR_LLM_CONNECT_TIMEOUT", "10")), float(_env("OBFUSCATOR_LLM_TIMEOUT", "180")))


_client_cache = {"client": None}


def _get_client() -> httpx.Client:
    if _client_cache["client"] is None:
        _client_cache["client"] = httpx.Client(
            base_url=base_url(), headers=_headers(), timeout=_timeout()
        )
    return _client_cache["client"]


def probe() -> dict:
    """Cheap availability check for /api/health. Never raises."""
    if not llm_enabled():
        return {"ready": False, "detail": "disabled"}
    try:
        res = _get_client().get("/models")
        res.raise_for_status()
        ids = [m.get("id") for m in res.json().get("data", [])]
        return {"ready": bool(ids), "models": ids}
    except Exception as exc:
        _client_cache["client"] = None
        return {"ready": False, "detail": f"{type(exc).__name__}: {exc}"}


def model_id(probe_result: dict) -> str | None:
    env = _env("OBFUSCATOR_LLM_MODEL", "")
    if env:
        return env
    models = probe_result.get("models") or []
    return models[0] if models else None


def chunk_text(text: str, size: int = _CHUNK_CHARS, overlap: int = _CHUNK_OVERLAP) -> list:
    """Exact slices: [(start, end, slice_text)] covering the whole text."""
    chunks = []
    pos = 0
    n = len(text)
    while pos < n:
        end = min(pos + size, n)
        chunks.append((pos, end, text[pos:end]))
        if end == n:
            break
        pos = end - overlap
    return chunks


def parse_json_array(raw: str) -> list:
    """Parse the model's reply tolerantly: strip code fences / prose, then
    take the outermost JSON array."""
    if not raw or not raw.strip():
        return []
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start = text.find("[")
    if start == -1:
        raise ValueError("no JSON array in reply")
    end = text.rfind("]")
    if end < start:
        raise ValueError("unterminated JSON array in reply")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, list):
        raise ValueError("reply is not an array")
    return parsed


def map_quotes(chunk_start: int, chunk_text_: str, items: list) -> tuple:
    """Return (findings, unverified). Each valid item becomes one finding per
    verbatim occurrence of its quote within the chunk."""
    findings = []
    unverified = []
    for item in items:
        if not isinstance(item, dict):
            unverified.append({"item": item, "reason": "not an object"})
            continue
        quote = item.get("quote")
        category = item.get("category")
        if not isinstance(quote, str) or len(quote.strip()) < 3:
            unverified.append({**item, "reason": "quote too short"})
            continue
        if category not in _CATEGORIES:
            unverified.append({**item, "reason": "unknown category"})
            continue
        try:
            raw = float(item.get("confidence", 0))
        except (TypeError, ValueError):
            unverified.append({**item, "reason": "bad confidence"})
            continue
        # Trust tier: LLM signals capped below the NER range.
        confidence = min(_TRUST_CAP, max(0.0, raw)) * 0.8
        found = False
        search_at = 0
        while True:
            idx = chunk_text_.find(quote, search_at)
            if idx == -1:
                break
            found = True
            findings.append(
                {
                    "start": chunk_start + idx,
                    "end": chunk_start + idx + len(quote),
                    "quote": quote,
                    "category": category,
                    "source": "llm",
                    "confidence": round(confidence, 4),
                    "reason": item.get("reason", ""),
                }
            )
            search_at = idx + len(quote)
        if not found:
            unverified.append({**item, "mapping_reason": "quote not found verbatim in text"})
    return findings, unverified


def _chat(client: httpx.Client, model: str, chunk: str) -> list:
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": PROMPT_SYSTEM},
            {"role": "user", "content": chunk},
        ],
    }
    res = client.post("/chat/completions", json=payload)
    res.raise_for_status()
    data = res.json()
    return data["choices"][0]["message"]["content"]


def detect(text: str) -> tuple:
    """Run Pass 2 over plain text. Returns (findings, unverified, errors)."""
    findings = []
    unverified = []
    errors = []
    if not llm_enabled() or not text.strip():
        return findings, unverified, errors
    probe_result = probe()
    if not probe_result.get("ready"):
        errors.append(f"llm unavailable: {probe_result.get('detail', 'no models loaded')}")
        return findings, unverified, errors
    model = model_id(probe_result)
    if not model:
        errors.append("llm unavailable: no model id")
        return findings, unverified, errors
    client = _get_client()
    for chunk_start, chunk_end, chunk_data in chunk_text(text):
        try:
            reply = _chat(client, model, chunk_data)
            items = parse_json_array(reply)
        except httpx.HTTPStatusError as exc:
            errors.append(f"llm http {exc.response.status_code}")
            _client_cache["client"] = None
            continue
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"llm error: {type(exc).__name__}: {exc}")
            continue
        chunk_findings, chunk_unverified = map_quotes(chunk_start, chunk_data, items)
        findings.extend(chunk_findings)
        unverified.extend(chunk_unverified)
    deduped = []
    seen = set()
    for f in findings:
        key = (f["start"], f["end"], f["category"])
        if key not in seen:
            seen.add(key)
            deduped.append(f)
    findings = deduped
    findings.sort(key=lambda f: (f["start"], -(f["end"] - f["start"])))
    return findings, unverified, errors
