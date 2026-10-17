"""Public-source narrative-to-token radar. Alerts only; never executes trades."""
from __future__ import annotations
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional
import requests


STOP = {"the", "and", "for", "with", "from", "tool", "open", "source", "project", "app", "api",
        "linux", "windows", "crypto", "token", "game", "using", "this", "that"}


def terms(text: str) -> List[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,24}", text or "")
    seen = []
    for word in words:
        key = word.lower().strip("_-")
        if key not in STOP and key not in seen:
            seen.append(key)
    return seen[:6]


def score_pair(pair: Dict[str, Any], narrative: Dict[str, Any], now_ms: int) -> Dict[str, Any]:
    liquidity = float((pair.get("liquidity") or {}).get("usd") or 0)
    volume = float((pair.get("volume") or {}).get("h24") or 0)
    tx = pair.get("txns") or {}
    h24 = tx.get("h24") or {}
    buys, sells = int(h24.get("buys") or 0), int(h24.get("sells") or 0)
    created = int(pair.get("pairCreatedAt") or now_ms)
    age_hours = max(0.0, (now_ms-created)/3_600_000)
    fdv = float(pair.get("fdv") or pair.get("marketCap") or 0)
    score = min(25, narrative.get("attention_score", 0)*0.25)
    score += 18 if liquidity >= 50_000 else (9 if liquidity >= 10_000 else 0)
    score += 15 if volume >= 100_000 else (7 if volume >= 20_000 else 0)
    score += 12 if buys >= 100 and buys > sells else (5 if buys > sells else 0)
    score += 8 if 1 <= age_hours <= 168 else 2
    score += 7 if 20_000 <= fdv <= 5_000_000 else 0
    risks = []
    if liquidity < 10_000: risks.append("thin_liquidity")
    if fdv and liquidity/fdv < 0.02: risks.append("low_liquidity_to_fdv")
    if sells == 0 and buys > 20: risks.append("sellability_unproven")
    if age_hours < 1: risks.append("extremely_new_pair")
    official = False  # must be proven via project-owned link; name matching is not proof.
    risks.append("unverified_project_affiliation")
    return {"chain": pair.get("chainId"), "dex": pair.get("dexId"),
        "pair_address": pair.get("pairAddress"), "token_address": (pair.get("baseToken") or {}).get("address"),
        "token_name": (pair.get("baseToken") or {}).get("name"), "symbol": (pair.get("baseToken") or {}).get("symbol"),
        "url": pair.get("url"), "liquidity_usd": round(liquidity, 2), "volume_24h": round(volume, 2),
        "buys_24h": buys, "sells_24h": sells, "age_hours": round(age_hours, 1), "fdv": round(fdv, 2),
        "score": round(max(0, min(100, score-len(risks)*3)), 1), "official_affiliation": official,
        "risks": risks, "action": "alert_only"}


class NarrativeRadar:
    def __init__(self, timeout=12, session: Optional[requests.Session] = None):
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "INETCRYP-public-research/1.0"})

    def github(self) -> List[Dict[str, Any]]:
        since = (datetime.now(timezone.utc)-timedelta(days=7)).date().isoformat()
        response = self.session.get("https://api.github.com/search/repositories",
            params={"q": f"created:>{since} stars:>100", "sort": "stars", "order": "desc", "per_page": 20},
            timeout=self.timeout)
        response.raise_for_status()
        rows = []
        for repo in response.json().get("items", []):
            stars = int(repo.get("stargazers_count") or 0)
            rows.append({"source": "github", "name": repo.get("name"), "title": repo.get("full_name"),
                "description": repo.get("description") or "", "url": repo.get("html_url"),
                "attention_score": min(100, 25+stars/100), "evidence": {"stars": stars,
                "forks": int(repo.get("forks_count") or 0), "created_at": repo.get("created_at")}})
        return rows

    def hackernews(self) -> List[Dict[str, Any]]:
        after = int(time.time()-3*86400)
        response = self.session.get("https://hn.algolia.com/api/v1/search_by_date",
            params={"tags": "story", "numericFilters": f"created_at_i>{after},points>30", "hitsPerPage": 20},
            timeout=self.timeout)
        response.raise_for_status()
        rows = []
        for hit in response.json().get("hits", []):
            title = hit.get("title") or ""
            points = int(hit.get("points") or 0)
            rows.append({"source": "hackernews", "name": (terms(title) or [""])[0], "title": title,
                "description": title, "url": hit.get("url") or "https://news.ycombinator.com/item?id="+str(hit.get("objectID")),
                "attention_score": min(100, 20+points/5), "evidence": {"points": points,
                "comments": int(hit.get("num_comments") or 0)}})
        return rows

    def dex_pairs(self, narrative: Dict[str, Any]) -> List[Dict[str, Any]]:
        query_terms = terms(" ".join([str(narrative.get("name") or ""), str(narrative.get("title") or "")]))[:2]
        found, now_ms = [], int(time.time()*1000)
        for query in query_terms:
            try:
                response = self.session.get("https://api.dexscreener.com/latest/dex/search",
                    params={"q": query}, timeout=self.timeout)
                response.raise_for_status()
                for pair in response.json().get("pairs") or []:
                    token_text = " ".join([str((pair.get("baseToken") or {}).get("name") or ""),
                        str((pair.get("baseToken") or {}).get("symbol") or "")]).lower()
                    if query.lower() in token_text:
                        found.append(score_pair(pair, narrative, now_ms))
            except Exception:
                continue
        unique = {row["pair_address"]: row for row in found if row.get("pair_address")}
        return sorted(unique.values(), key=lambda row: -row["score"])[:5]

    def scan(self) -> Dict[str, Any]:
        narratives, errors = [], []
        for name, loader in (("github", self.github), ("hackernews", self.hackernews)):
            try: narratives.extend(loader())
            except Exception as exc: errors.append({"source": name, "error_type": type(exc).__name__})
        narratives = sorted(narratives, key=lambda row: -row["attention_score"])[:20]
        results = []
        for narrative in narratives:
            pairs = self.dex_pairs(narrative)
            if pairs:
                results.append({**narrative, "token_candidates": pairs})
        return {"status": "ok" if narratives else "degraded", "generated_at": datetime.now(timezone.utc).isoformat(),
            "sources": ["github", "hackernews", "dexscreener"], "x_coverage": False,
            "errors": errors, "narratives_checked": len(narratives), "matches": results,
            "warning": "Name matching does not prove token affiliation. Alert only; never auto-buy."}
