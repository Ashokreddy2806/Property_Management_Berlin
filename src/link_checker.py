import concurrent.futures
import datetime
import logging
from typing import Dict, Any, List
import requests
import urllib3
from config import USER_AGENT, REQUEST_TIMEOUT, AGGREGATOR_DOMAINS

# Suppress insecure HTTPS warnings if testing self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

def check_single_link(website: str) -> Dict[str, Any]:
    """
    Checks website availability using HEAD with fallback to GET.
    Returns status_code, final_url, ssl_ok, checked_at, and website_status.
    """
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if not website or website.lower() in ["unknown", "none", ""]:
        return {
            "website_status": "none",
            "final_url": "",
            "status_code": 0,
            "ssl_ok": False,
            "checked_at": now_str,
        }

    url = website.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    # First check HTTP cache variants (http/https, www/non-www, trailing slash)
    from src.cache import get_cached_http
    from urllib.parse import urlparse
    import json
    from config import DATA_CACHE_DIR

    parsed = urlparse(url)
    dom = parsed.netloc.lower()
    if dom.startswith("www."):
        clean_dom = dom[4:]
    else:
        clean_dom = dom

    variants = [
        url,
        url.rstrip("/") if url.endswith("/") else url + "/",
        f"https://{clean_dom}",
        f"https://{clean_dom}/",
        f"http://{clean_dom}",
        f"http://{clean_dom}/",
        f"https://www.{clean_dom}",
        f"https://www.{clean_dom}/",
        f"http://www.{clean_dom}",
        f"http://www.{clean_dom}/",
    ]

    def _is_aggregator(candidate: str) -> bool:
        candidate_domain = urlparse(candidate).netloc.lower().split(":")[0]
        if candidate_domain.startswith("www."):
            candidate_domain = candidate_domain[4:]
        return any(
            candidate_domain == domain or candidate_domain.endswith(f".{domain}")
            for domain in AGGREGATOR_DOMAINS
        )

    for cand in variants:
        cached = get_cached_http(cand)
        if cached and "status_code" in cached:
            status_code = cached["status_code"]
            cached_url = cached.get("url", cand)
            if 200 <= status_code < 400 and not _is_aggregator(cached_url):
                return {
                    "website_status": "ok",
                    "final_url": cached_url,
                    "status_code": status_code,
                    "ssl_ok": True,
                    "checked_at": cached.get("timestamp", now_str),
                }

    # Check goto_resolved_map.json
    goto_p = DATA_CACHE_DIR / "goto_resolved_map.json"
    if goto_p.exists():
        try:
            with open(goto_p, "r", encoding="utf-8") as f:
                gmap = json.load(f)
            mapped_target = gmap.get(url)
            if not mapped_target:
                mapped_target = next(
                    (target for source, target in gmap.items() if source.lower() == url.lower()),
                    None,
                )
            if mapped_target and not _is_aggregator(mapped_target):
                return {
                    "website_status": "ok",
                    "final_url": mapped_target,
                    "status_code": 200,
                    "ssl_ok": True,
                    "checked_at": now_str,
                }
            for tgt in gmap.values():
                tgt_dom = urlparse(tgt).netloc.lower()
                if tgt_dom.startswith("www."):
                    tgt_dom = tgt_dom[4:]
                if tgt_dom == clean_dom and not _is_aggregator(tgt):
                    return {
                        "website_status": "ok",
                        "final_url": tgt,
                        "status_code": 200,
                        "ssl_ok": True,
                        "checked_at": now_str,
                    }
        except Exception:
            pass

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        # Try HEAD first
        resp = requests.head(url, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=True, verify=True)
        # If server returns 405 Method Not Allowed or 403 on HEAD, fallback to GET
        if resp.status_code in [403, 405, 500]:
            resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=True, stream=True, verify=True)
            
        ssl_ok = True
        status_code = resp.status_code
        final_url = resp.url
        is_redirect = (url.rstrip("/") != final_url.rstrip("/"))

        if 200 <= status_code < 400 and not _is_aggregator(final_url):
            status = "ok"
        elif 200 <= status_code < 400:
            status = "none"
        else:
            status = "dead"

        return {
            "website_status": status,
            "final_url": final_url,
            "status_code": status_code,
            "ssl_ok": ssl_ok,
            "checked_at": now_str,
        }
    except requests.exceptions.SSLError:
        # Try without strict SSL verify
        try:
            resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=True, stream=True, verify=False)
            status_code = resp.status_code
            status = "ok" if 200 <= status_code < 400 and not _is_aggregator(resp.url) else "none"
            return {
                "website_status": status,
                "final_url": resp.url,
                "status_code": status_code,
                "ssl_ok": False,
                "checked_at": now_str,
            }
        except Exception:
            return {
                "website_status": "dead",
                "final_url": url,
                "status_code": 0,
                "ssl_ok": False,
                "checked_at": now_str,
            }
    except Exception:
        return {
            "website_status": "dead",
            "final_url": url,
            "status_code": 0,
            "ssl_ok": False,
            "checked_at": now_str,
        }

def check_all_links(leads: List[Dict[str, Any]], max_workers: int = 15) -> List[Dict[str, Any]]:
    """
    Checks links across all leads in parallel threads.
    """
    logger.info(f"Checking links for {len(leads)} leads...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {
            executor.submit(check_single_link, lead.get("website", "")): idx
            for idx, lead in enumerate(leads)
        }
        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            res = future.result()
            leads[idx]["website_status"] = res["website_status"]
            leads[idx]["final_url"] = res["final_url"]
            leads[idx]["status_code"] = res["status_code"]
            leads[idx]["ssl_ok"] = res["ssl_ok"]
            leads[idx]["checked_at"] = res["checked_at"]

    alive = sum(1 for l in leads if l.get("website_status") in ["ok", "redirected"])
    dead = sum(1 for l in leads if l.get("website_status") == "dead")
    none = sum(1 for l in leads if l.get("website_status") == "none")
    logger.info(f"Link check complete: {alive} alive ({round(alive/len(leads)*100, 1)}%), {dead} dead, {none} without website.")
    return leads
