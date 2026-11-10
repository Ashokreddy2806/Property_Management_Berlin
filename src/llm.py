import json
import os
import time
from pathlib import Path
from typing import Optional, Dict, Any
import requests
import dotenv
from config import NVIDIA_API_KEY, GEMINI_API_KEY, GEMINI_MODEL, LOGS_DIR
from src.cache import get_cached_llm, set_cached_llm

LLM_LOG_FILE = LOGS_DIR / "llm_calls.jsonl"

def log_llm_call(stage: str, model: str, latency_ms: float, cache_hit: bool, tokens: Optional[dict] = None, prompt: str = ""):
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stage": stage,
        "model": model,
        "latency_ms": round(latency_ms, 2),
        "cache_hit": cache_hit,
        "tokens": tokens or {},
        "prompt_preview": prompt[:150].replace("\n", " "),
    }
    with open(LLM_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def call_llm(prompt: str, stage: str = "general", system_prompt: Optional[str] = None, max_tokens: int = 2048, retries: int = 2) -> str:
    """
    Unified LLM call supporting NVIDIA Nemotron (with OpenAI-compatible endpoint) and caching.
    Handles streaming/non-streaming and extracts response text cleanly.
    """
    model = GEMINI_MODEL or "nvidia/nemotron-3.5-bolt-e4b"
    
    # Check cache
    full_prompt = f"SYSTEM: {system_prompt}\nUSER: {prompt}" if system_prompt else prompt
    cached = get_cached_llm(full_prompt, model)
    if cached is not None:
        log_llm_call(stage=stage, model=model, latency_ms=0.0, cache_hit=True, prompt=full_prompt)
        return cached

    start_time = time.time()
    api_key = NVIDIA_API_KEY
    if not api_key:
        raise ValueError("Missing NVIDIA_API_KEY in environment variables (.env)")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": max_tokens,
    }

    last_error = None
    for attempt in range(retries + 1):
        try:
            # First try non-streaming
            resp = requests.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=45
            )
            
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"] or ""
                latency_ms = (time.time() - start_time) * 1000
                tokens = data.get("usage", {})
                
                # Cache response
                set_cached_llm(full_prompt, model, content, {"usage": tokens})
                log_llm_call(stage=stage, model=model, latency_ms=latency_ms, cache_hit=False, tokens=tokens, prompt=full_prompt)
                return content
            elif resp.status_code == 429:
                time.sleep(2 ** (attempt + 1))
                continue
            else:
                # If non-streaming returned error, try streaming fallback
                stream_headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "text/event-stream"
                }
                stream_payload = {**payload, "stream": True}
                stream_resp = requests.post(
                    "https://integrate.api.nvidia.com/v1/chat/completions",
                    headers=stream_headers,
                    json=stream_payload,
                    stream=True,
                    timeout=60
                )
                if stream_resp.status_code == 200:
                    chunks = []
                    usage = {}
                    for line in stream_resp.iter_lines():
                        if not line:
                            continue
                        line_str = line.decode("utf-8")
                        if line_str.startswith("data: ") and line_str != "data: [DONE]":
                            try:
                                chunk_json = json.loads(line_str[6:])
                                choices = chunk_json.get("choices", [])
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    txt = delta.get("content")
                                    if txt:
                                        chunks.append(txt)
                                if "usage" in chunk_json and chunk_json["usage"]:
                                    usage = chunk_json["usage"]
                            except Exception:
                                pass
                    content = "".join(chunks).strip()
                    latency_ms = (time.time() - start_time) * 1000
                    set_cached_llm(full_prompt, model, content, {"usage": usage})
                    log_llm_call(stage=stage, model=model, latency_ms=latency_ms, cache_hit=False, tokens=usage, prompt=full_prompt)
                    return content
                else:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    time.sleep(2)
        except Exception as e:
            last_error = str(e)
            time.sleep(2)

    raise RuntimeError(f"LLM call failed after {retries+1} attempts: {last_error}")

def call_llm_json(prompt: str, stage: str = "general", system_prompt: Optional[str] = None, retries: int = 2) -> Dict[str, Any]:
    """
    Calls LLM and guarantees a parsed JSON dict. Strips markdown fences (```json ... ```).
    """
    json_instructions = "\n\nCRITICAL: Respond ONLY with a valid JSON object. Do not include markdown code blocks or explanatory text outside the JSON."
    augmented_prompt = prompt + json_instructions
    
    for attempt in range(retries + 1):
        raw = call_llm(augmented_prompt, stage=stage, system_prompt=system_prompt)
        # Clean markdown code blocks
        clean = raw.strip()
        if clean.startswith("```json"):
            clean = clean[7:]
        elif clean.startswith("```"):
            clean = clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        clean = clean.strip()
        
        # In case model output has reasoning or prefix text before first '{'
        first_brace = clean.find("{")
        last_brace = clean.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            clean = clean[first_brace:last_brace+1]

        try:
            return json.loads(clean)
        except json.JSONDecodeError as e:
            if attempt == retries:
                raise ValueError(f"Failed to parse LLM JSON: {e}\nRaw output: {raw[:300]}")
            time.sleep(1)
