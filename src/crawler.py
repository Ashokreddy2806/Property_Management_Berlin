import json
import logging
import re
import time
from urllib.parse import urljoin, urlparse
from typing import Dict, Any, List, Set, Optional
import requests
from bs4 import BeautifulSoup
import trafilatura
from config import (
    USER_AGENT, REQUEST_TIMEOUT, CRAWL_DELAY_PER_HOST,
    MAX_INTERNAL_PAGES_PER_SITE, PAGE_KEYWORDS
)
from src.cache import get_cached_http, set_cached_http

logger = logging.getLogger(__name__)

# Track host access timestamps for politeness
_HOST_LAST_ACCESS: Dict[str, float] = {}

def _respect_politeness(host: str):
    last = _HOST_LAST_ACCESS.get(host, 0)
    elapsed = time.time() - last
    if elapsed < CRAWL_DELAY_PER_HOST:
        time.sleep(CRAWL_DELAY_PER_HOST - elapsed)
    _HOST_LAST_ACCESS[host] = time.time()

def fetch_page_text(url: str) -> Optional[Dict[str, str]]:
    """
    Fetches a page, respects cache, cleans HTML to plain text via trafilatura or BeautifulSoup.
    Returns dict with {"url": url, "text": text} or None.
    """
    cached = get_cached_http(url)
    html = ""
    status_code = 200
    if cached:
        html = cached.get("text", "")
    else:
        parsed = urlparse(url)
        _respect_politeness(parsed.netloc)
        headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
        try:
            resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT, verify=False)
            if resp.status_code == 200:
                html = resp.text
                set_cached_http(url, resp.status_code, html)
            else:
                return None
        except Exception:
            return None

    if not html:
        return None

    # Extract text with trafilatura
    text = trafilatura.extract(html, include_links=False, include_images=False, favor_precision=True)
    if not text or len(text.strip()) < 50:
        # Fallback to BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)

    clean_text = re.sub(r"\n\s*\n", "\n\n", text).strip()
    return {"url": url, "text": clean_text}

def find_internal_target_links(base_url: str, html: str) -> List[str]:
    """
    Finds internal links matching keywords: impressum, kontakt, team, ueber-uns, leistungen, karriere, portal, etc.
    """
    soup = BeautifulSoup(html, "html.parser")
    base_domain = urlparse(base_url).netloc.lower()
    if base_domain.startswith("www."):
        base_domain = base_domain[4:]

    found_links: Set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        link_text = a.get_text().strip().lower()
        if not href or href.startswith("javascript:") or href.startswith("mailto:") or href.startswith("tel:"):
            continue

        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)
        link_domain = parsed.netloc.lower()
        if link_domain.startswith("www."):
            link_domain = link_domain[4:]

        # Must be internal link
        if link_domain != base_domain:
            continue

        path_and_text = f"{parsed.path} {link_text}".lower()
        for kw in PAGE_KEYWORDS:
            if kw in path_and_text:
                clean_full = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                if clean_full != base_url.rstrip("/"):
                    found_links.add(clean_full)
                break

        if len(found_links) >= MAX_INTERNAL_PAGES_PER_SITE:
            break

    return list(found_links)[:MAX_INTERNAL_PAGES_PER_SITE]

def crawl_company_website(website: str, max_pages: int = MAX_INTERNAL_PAGES_PER_SITE) -> Dict[str, Any]:
    """
    Crawls homepage and up to max_pages relevant internal pages.
    Returns combined text, list of crawled page urls, and individual page texts.
    """
    if not website or website.lower() in ["unknown", "none"]:
        return {"pages_crawled": [], "text_by_url": {}, "combined_text": ""}

    start_url = website.strip()
    if not start_url.startswith("http://") and not start_url.startswith("https://"):
        start_url = "https://" + start_url

    homepage_res = fetch_page_text(start_url)
    if not homepage_res:
        return {"pages_crawled": [], "text_by_url": {}, "combined_text": ""}

    text_by_url: Dict[str, str] = {homepage_res["url"]: homepage_res["text"]}
    pages_crawled: List[str] = [homepage_res["url"]]

    # Fetch cached raw html to extract links
    cached_home = get_cached_http(start_url)
    home_html = cached_home.get("text", "") if cached_home else ""
    internal_links = find_internal_target_links(homepage_res["url"], home_html)

    for link in internal_links:
        if len(pages_crawled) >= max_pages + 1:
            break
        page_res = fetch_page_text(link)
        if page_res and page_res["text"]:
            text_by_url[page_res["url"]] = page_res["text"]
            pages_crawled.append(page_res["url"])

    # Combine text with clear page delimiter, capped at 25,000 chars
    combined_parts = []
    total_len = 0
    for u, txt in text_by_url.items():
        snippet = txt[:5000] # cap each page at 5000 chars
        combined_parts.append(f"--- PAGE SOURCE: {u} ---\n{snippet}\n")
        total_len += len(snippet)
        if total_len > 25000:
            break

    return {
        "pages_crawled": pages_crawled,
        "text_by_url": text_by_url,
        "combined_text": "\n".join(combined_parts)
    }
