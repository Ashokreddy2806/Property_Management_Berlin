import hashlib
import json
import time
import urllib.parse
from pathlib import Path
from typing import Optional, Any
from config import DATA_CACHE_DIR, PROMPT_VERSION

CACHE_HTTP_DIR = DATA_CACHE_DIR / "http"
CACHE_LLM_DIR = DATA_CACHE_DIR / "llm"

CACHE_HTTP_DIR.mkdir(parents=True, exist_ok=True)
CACHE_LLM_DIR.mkdir(parents=True, exist_ok=True)

SENSITIVE_PARAMS = {"api_key", "apikey", "key", "token"}

def sanitize_url(url: str) -> str:
    """Redacts sensitive query parameters (api_key, token, etc.) from a URL."""
    if not url or "?" not in url:
        return url
    parsed = urllib.parse.urlsplit(url)
    qs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    clean_qs = []
    for k, v in qs:
        if k.lower() in SENSITIVE_PARAMS:
            clean_qs.append((k, "REDACTED"))
        else:
            clean_qs.append((k, v))
    new_query = urllib.parse.urlencode(clean_qs)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment))

def sanitize_params(params: Optional[dict]) -> Optional[dict]:
    """Redacts sensitive keys from query parameter dictionaries."""
    if not params:
        return params
    clean = {}
    for k, v in params.items():
        if k.lower() in SENSITIVE_PARAMS:
            clean[k] = "REDACTED"
        else:
            clean[k] = v
    return clean

def _hash_key(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()

def get_cached_http(url: str, params: Optional[dict] = None, json_body: Optional[dict] = None) -> Optional[dict]:
    clean_url = sanitize_url(url)
    clean_params = sanitize_params(params)
    key_str = f"{clean_url}:{json.dumps(clean_params, sort_keys=True) if clean_params else ''}:{json.dumps(json_body, sort_keys=True) if json_body else ''}"
    key = _hash_key(key_str)
    file_path = CACHE_HTTP_DIR / f"{key}.json"
    if file_path.exists():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    # Fallback check for unredacted legacy key if not yet migrated
    raw_key_str = f"{url}:{json.dumps(params, sort_keys=True) if params else ''}:{json.dumps(json_body, sort_keys=True) if json_body else ''}"
    legacy_file = CACHE_HTTP_DIR / f"{_hash_key(raw_key_str)}.json"
    if legacy_file.exists():
        try:
            with open(legacy_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["url"] = clean_url
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            return data
        except Exception:
            return None

    return None

def set_cached_http(url: str, status_code: int, text: str, headers: Optional[dict] = None, params: Optional[dict] = None, json_body: Optional[dict] = None) -> None:
    clean_url = sanitize_url(url)
    clean_params = sanitize_params(params)
    key_str = f"{clean_url}:{json.dumps(clean_params, sort_keys=True) if clean_params else ''}:{json.dumps(json_body, sort_keys=True) if json_body else ''}"
    key = _hash_key(key_str)
    file_path = CACHE_HTTP_DIR / f"{key}.json"
    data = {
        "url": clean_url,
        "status_code": status_code,
        "text": text,
        "headers": headers or {},
        "timestamp": time.time(),
    }
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

def get_cached_llm(prompt: str, model: str, prompt_version: str = PROMPT_VERSION) -> Optional[str]:
    key_str = f"{model}:{prompt_version}:{prompt}"
    key = _hash_key(key_str)
    file_path = CACHE_LLM_DIR / f"{key}.json"
    if file_path.exists():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("response")
        except Exception:
            return None
    return None

def set_cached_llm(prompt: str, model: str, response: str, metadata: Optional[dict] = None, prompt_version: str = PROMPT_VERSION) -> None:
    key_str = f"{model}:{prompt_version}:{prompt}"
    key = _hash_key(key_str)
    file_path = CACHE_LLM_DIR / f"{key}.json"
    data = {
        "model": model,
        "prompt_version": prompt_version,
        "prompt": prompt,
        "response": response,
        "metadata": metadata or {},
        "timestamp": time.time(),
    }
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
