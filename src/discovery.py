import json
import logging
import re
import time
from typing import List, Dict, Any, Tuple
import requests
from bs4 import BeautifulSoup
from config import (
    BERLIN_BEZIRKE, DISCOVERY_KEYWORDS, SERPER_API_KEY, TAVILY_API_KEY,
    USER_AGENT, REQUEST_TIMEOUT, CRAWL_DELAY_PER_HOST
)
from src.cache import get_cached_http, set_cached_http
from src.agent_discovery import classify_company_discovery

logger = logging.getLogger(__name__)

def search_serper(query: str, num: int = 10, page: int = 1) -> List[Dict[str, Any]]:
    if not SERPER_API_KEY:
        return []

    url = "https://google.serper.dev/search"
    payload = {
        "q": query,
        "gl": "de",
        "hl": "de",
        "num": num,
        "page": page
    }
    
    cached = get_cached_http(url, json_body=payload)
    if cached:
        data = json.loads(cached["text"]) if isinstance(cached["text"], str) else cached["text"]
    else:
        try:
            resp = requests.post(
                url,
                headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
                json=payload,
                timeout=REQUEST_TIMEOUT
            )
            if resp.status_code == 200:
                data = resp.json()
                set_cached_http(url, resp.status_code, resp.text, json_body=payload)
            elif resp.status_code == 429:
                time.sleep(2)
                return []
            else:
                return []
        except Exception as e:
            logger.error(f"Serper request error: {e}")
            return []

    results = []
    for place in data.get("places", []):
        results.append({
            "company_name": place.get("title", ""),
            "website": place.get("website", ""),
            "address": place.get("address", "Berlin"),
            "phone": place.get("phoneNumber", "unknown"),
            "snippet": f"Category: {place.get('category', '')} Rating: {place.get('rating', '')}",
            "source": "serper_places",
            "source_url": place.get("website") or "https://google.serper.dev/places"
        })

    for org in data.get("organic", []):
        results.append({
            "company_name": org.get("title", ""),
            "website": org.get("link", ""),
            "address": "Berlin",
            "phone": "unknown",
            "snippet": org.get("snippet", ""),
            "source": "serper_organic",
            "source_url": org.get("link", "")
        })

    return results

def search_serper_places(query: str) -> List[Dict[str, Any]]:
    if not SERPER_API_KEY:
        return []

    url = "https://google.serper.dev/places"
    payload = {"q": query, "gl": "de", "hl": "de"}
    
    cached = get_cached_http(url, json_body=payload)
    if cached:
        data = json.loads(cached["text"]) if isinstance(cached["text"], str) else cached["text"]
    else:
        try:
            resp = requests.post(
                url,
                headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
                json=payload,
                timeout=REQUEST_TIMEOUT
            )
            if resp.status_code == 200:
                data = resp.json()
                set_cached_http(url, resp.status_code, resp.text, json_body=payload)
            else:
                return []
        except Exception:
            return []

    results = []
    for place in data.get("places", []):
        results.append({
            "company_name": place.get("title", "").strip(),
            "website": place.get("website", "").strip(),
            "address": place.get("address", "Berlin").strip(),
            "phone": place.get("phoneNumber", "unknown").strip(),
            "snippet": f"Google Places Category: {place.get('category', '')} Rating: {place.get('rating', '')} ({place.get('reviewsCount', 0)} reviews)",
            "source": "serper_places_api",
            "source_url": place.get("website") or "https://maps.google.com"
        })
    return results

def scrape_gelbe_seiten_berlin(max_pages: int = 8) -> List[Dict[str, Any]]:
    leads = []
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}

    for page in range(1, max_pages + 1):
        url = f"https://www.gelbeseiten.de/suche/hausverwaltung/berlin/seite-{page}" if page > 1 else "https://www.gelbeseiten.de/suche/hausverwaltung/berlin"
        cached = get_cached_http(url)
        if cached:
            html = cached.get("text", "")
        else:
            try:
                time.sleep(1.2)
                resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
                if resp.status_code == 200:
                    html = resp.text
                    set_cached_http(url, resp.status_code, html)
                else:
                    break
            except Exception:
                break

        soup = BeautifulSoup(html, "html.parser")
        articles = soup.select("article")
        if not articles:
            break

        for art in articles:
            h2 = art.find("h2")
            name = h2.get_text(strip=True) if h2 else ""
            if not name:
                continue

            addr_tag = art.find("address")
            addr_text = addr_tag.get_text(" ", strip=True) if addr_tag else "Berlin"
            addr_clean = re.sub(r"\d+([.,]\d+)?\s*km.*", "", addr_text).strip()

            phone_tag = art.find("a", href=lambda h: h and "tel:" in h) or art.find(class_=lambda c: c and "phone" in c.lower())
            phone_text = phone_tag.get_text(strip=True) if phone_tag else "unknown"

            leads.append({
                "company_name": name,
                "website": "",
                "address": addr_clean or "Berlin",
                "phone": phone_text,
                "snippet": f"Gelbe Seiten Directory: Hausverwaltung Berlin ({addr_clean})",
                "source": "gelbe_seiten",
                "source_url": url
            })

    return leads

def scrape_das_oertliche_berlin(max_pages: int = 5) -> List[Dict[str, Any]]:
    leads = []
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}

    for page in range(1, max_pages + 1):
        url = f"https://www.dasoertliche.de/Themen/Hausverwaltung/Berlin/seite-{page}.html" if page > 1 else "https://www.dasoertliche.de/Themen/Hausverwaltung/Berlin.html"
        cached = get_cached_http(url)
        if cached:
            html = cached.get("text", "")
        else:
            try:
                time.sleep(1.2)
                resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
                if resp.status_code == 200:
                    html = resp.text
                    set_cached_http(url, resp.status_code, html)
                else:
                    break
            except Exception:
                break

        soup = BeautifulSoup(html, "html.parser")
        hits = soup.select(".hit, article, [data-entry-id]")
        if not hits:
            break

        for h in hits:
            name_tag = h.select_one("a.name, h2, .hit-name")
            name = name_tag.get_text(strip=True) if name_tag else ""
            if not name:
                continue

            addr_tag = h.select_one("address, .address")
            addr = addr_tag.get_text(" ", strip=True) if addr_tag else "Berlin"

            phone_tag = h.select_one("a[href^='tel:'], .phone, [data-phone]")
            phone = phone_tag.get_text(strip=True) if phone_tag else "unknown"

            leads.append({
                "company_name": name,
                "website": "",
                "address": addr or "Berlin",
                "phone": phone,
                "snippet": f"Das Örtliche Directory: Hausverwaltung Berlin ({addr})",
                "source": "das_oertliche",
                "source_url": url
            })

    return leads

def query_osm_overpass() -> List[Dict[str, Any]]:
    endpoints = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter"
    ]
    query = """
    [out:json][timeout:15];
    area["name"="Berlin"]["admin_level"="4"]->.searchArea;
    (
      node["office"="property_management"](area.searchArea);
      way["office"="property_management"](area.searchArea);
      node["office"="estate_agent"]["name"~"Hausverwaltung|Immobilienverwaltung|WEG",i](area.searchArea);
    );
    out body 200;
    >;
    out skel qt;
    """
    data = None
    for url in endpoints:
        cached = get_cached_http(url, json_body={"q": query})
        if cached:
            data = json.loads(cached["text"]) if isinstance(cached["text"], str) else cached["text"]
            break
        try:
            resp = requests.post(url, data={"data": query}, headers={"User-Agent": USER_AGENT}, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                set_cached_http(url, resp.status_code, resp.text, json_body={"q": query})
                break
        except Exception:
            continue

    if not data:
        return []

    leads = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        street = tags.get("addr:street", "")
        housenumber = tags.get("addr:housenumber", "")
        postcode = tags.get("addr:postcode", "")
        city = tags.get("addr:city", "Berlin")
        addr_parts = [p for p in [f"{street} {housenumber}".strip(), f"{postcode} {city}".strip()] if p]
        address = ", ".join(addr_parts) if addr_parts else "Berlin"
        website = tags.get("website") or tags.get("contact:website") or ""
        phone = tags.get("phone") or tags.get("contact:phone") or "unknown"

        leads.append({
            "company_name": name.strip(),
            "website": website.strip(),
            "address": address,
            "phone": phone.strip(),
            "snippet": f"OSM Property Management Office: {tags.get('office', '')}",
            "source": "osm_overpass",
            "source_url": website or "https://www.openstreetmap.org"
        })
    return leads

def query_tavily_directory() -> List[Dict[str, Any]]:
    if not TAVILY_API_KEY:
        return []
        
    url = "https://api.tavily.com/search"
    queries = [
        "Berliner Hausverwaltungen Liste Verzeichnis",
        "VDIV Berlin Brandenburg Hausverwaltung Mitglieder",
        "WEG Verwaltung Berlin Immobilienverwaltung Liste",
        "Mietverwaltung Berlin Hausverwaltungen Firmen",
        "Hausverwaltungen Berlin Charlottenburg Wilmersdorf Steglitz Liste",
        "Hausverwaltung Berlin Köpenick Pankow Reinickendorf Liste"
    ]
    
    results = []
    for q in queries:
        payload = {"api_key": TAVILY_API_KEY, "query": q, "max_results": 10, "search_depth": "basic"}
        cached = get_cached_http(url, json_body={"q": q})
        if cached:
            data = json.loads(cached["text"]) if isinstance(cached["text"], str) else cached["text"]
        else:
            try:
                resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
                if resp.status_code == 200:
                    data = resp.json()
                    set_cached_http(url, resp.status_code, resp.text, json_body={"q": q})
                else:
                    continue
            except Exception:
                continue

        for item in data.get("results", []):
            title = item.get("title", "")
            company = title.split(" - ")[0].split(" | ")[0].split(" – ")[0].strip()
            results.append({
                "company_name": company,
                "website": item.get("url", ""),
                "address": "Berlin",
                "phone": "unknown",
                "snippet": item.get("content", ""),
                "source": "tavily_search",
                "source_url": item.get("url", "")
            })
    return results

def run_full_discovery(max_serper_pages: int = 4) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    raw_candidates = []

    # 1. Google Places via Serper (12 Bezirke + top PLZ clusters)
    logger.info("Discovering from Google Places via Serper (12 Bezirke + top PLZ)...")
    for b in BERLIN_BEZIRKE:
        for kw in ["Hausverwaltung", "WEG-Verwaltung", "Immobilienverwaltung"]:
            places = search_serper_places(f"{kw} Berlin {b}")
            raw_candidates.extend(places)
            time.sleep(0.05)
            
    # Add top postal code places
    top_plz = ["10115", "10707", "10435", "12165", "13581", "10245", "12043", "14195", "13353", "10315", "12435", "12627"]
    for plz in top_plz:
        places = search_serper_places(f"Hausverwaltung {plz} Berlin")
        raw_candidates.extend(places)
        time.sleep(0.05)
    logger.info(f"Google Places discovered: {len(raw_candidates)} entries.")

    # 2. Serper Organic Search (12 Bezirke x 5 keywords, pages 1 to 4)
    logger.info(f"Discovering from Google Search via Serper (12 Bezirke x 5 terms, up to page {max_serper_pages})...")
    serper_count = 0
    for bezirk in BERLIN_BEZIRKE:
        for kw in DISCOVERY_KEYWORDS:
            query = f"{kw} Berlin {bezirk}"
            for p in range(1, max_serper_pages + 1):
                leads = search_serper(query, num=10, page=p)
                raw_candidates.extend(leads)
                serper_count += len(leads)
                time.sleep(0.05)
    logger.info(f"Serper Search added {serper_count} entries.")

    # 3. Gelbe Seiten Berlin (pages 1 to 8)
    logger.info("Discovering from Gelbe Seiten Berlin (pages 1-8)...")
    gs_leads = scrape_gelbe_seiten_berlin(max_pages=8)
    logger.info(f"Gelbe Seiten returned {len(gs_leads)} entries.")
    raw_candidates.extend(gs_leads)

    # 4. Das Örtliche Berlin (pages 1 to 5)
    logger.info("Discovering from Das Örtliche Berlin (pages 1-5)...")
    do_leads = scrape_das_oertliche_berlin(max_pages=5)
    logger.info(f"Das Örtliche returned {len(do_leads)} entries.")
    raw_candidates.extend(do_leads)

    # 5. Tavily Supplement
    logger.info("Discovering from Tavily search...")
    tavily_leads = query_tavily_directory()
    logger.info(f"Tavily returned {len(tavily_leads)} entries.")
    raw_candidates.extend(tavily_leads)

    # 6. OSM Overpass
    osm_leads = query_osm_overpass()
    if osm_leads:
        logger.info(f"OSM Overpass returned {len(osm_leads)} entries.")
        raw_candidates.extend(osm_leads)

    logger.info(f"Total raw candidates collected across all sources: {len(raw_candidates)}")

    # 7. Filter and segment with Agent 1
    qualified_leads = []
    excluded_leads = []

    for cand in raw_candidates:
        name = cand.get("company_name", "").strip()
        if not name or len(name) < 3:
            continue
            
        classification = classify_company_discovery(
            name=name,
            snippet=cand.get("snippet", ""),
            website=cand.get("website", "")
        )
        
        cand["segment"] = classification["segment"]
        cand["exclusion_reason"] = classification["reason"]

        if cand["segment"] == "Other/not a Hausverwaltung":
            excluded_leads.append(cand)
        else:
            qualified_leads.append(cand)

    logger.info(f"Discovery complete: {len(qualified_leads)} qualified candidates, {len(excluded_leads)} excluded.")
    return qualified_leads, excluded_leads
