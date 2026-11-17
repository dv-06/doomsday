"""Polite HTTP client: timeouts, bounded retries, robots.txt awareness.

We never solve, spoof or work around a challenge page. If a source answers with
an anti-bot interstitial we classify it as ``blocked`` and say so in the UI.
"""

from __future__ import annotations

import json
import random
import time
import urllib.robotparser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

CHALLENGE_MARKERS = (
    "just a moment",
    "cf-chl",
    "__cf_chl",
    "challenge-platform",
    "attention required",
    "verify you are human",
    "captcha",
    "access denied",
    "request blocked",
)


@dataclass
class FetchResult:
    url: str
    status: str  # ok | http_error | blocked | timeout | network_error | robots_disallowed
    http_status: int | None = None
    text: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    latency_ms: int = 0
    attempts: int = 0
    error: str | None = None
    blocked_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def evidence(self) -> dict[str, Any]:
        """Small, non-secret record used in data/sources.json and the Sources page."""
        return {
            "url": self.url,
            "status": self.status,
            "http_status": self.http_status,
            "latency_ms": self.latency_ms,
            "attempts": self.attempts,
            "error": self.error,
            "blocked_reason": self.blocked_reason,
        }


class RobotsCache:
    """Caches robots.txt per host. Unavailable robots.txt is treated as allow-all."""

    def __init__(self, user_agent: str, cache_dir: Path | None = None, ttl_seconds: int = 86400) -> None:
        self.user_agent = user_agent
        self.cache_dir = cache_dir
        self.ttl_seconds = ttl_seconds
        self._parsers: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _cache_path(self, host: str) -> Path | None:
        if not self.cache_dir:
            return None
        return self.cache_dir / f"robots-{host.replace(':', '_')}.json"

    def _load(self, host: str) -> tuple[str, float] | None:
        path = self._cache_path(host)
        if not path or not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload["body"], float(payload["fetched_at"])
        except (OSError, ValueError, KeyError):
            return None

    def _store(self, host: str, body: str) -> None:
        path = self._cache_path(host)
        if not path:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"body": body, "fetched_at": time.time()}), encoding="utf-8")
        except OSError:
            pass

    def allowed(self, url: str, client: "HttpClient") -> bool:
        parsed = urlparse(url)
        if not parsed.scheme.startswith("http"):
            return True
        host = parsed.netloc
        if host not in self._parsers:
            parser: urllib.robotparser.RobotFileParser | None
            cached = self._load(host)
            body: str | None = cached[0] if cached and time.time() - cached[1] < self.ttl_seconds else None
            if body is None:
                res = client.get(f"{parsed.scheme}://{host}/robots.txt", respect_robots=False, retries=0)
                if res.ok:
                    body = res.text
                    self._store(host, body)
            if body:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(body.splitlines())
            else:
                parser = None
            self._parsers[host] = parser
        parser = self._parsers[host]
        if parser is None:
            return True
        try:
            return parser.can_fetch(self.user_agent, url)
        except Exception:  # pragma: no cover - defensive, malformed robots.txt
            return True


class HttpClient:
    def __init__(
        self,
        *,
        user_agent: str,
        timeout_seconds: float = 25.0,
        max_retries: int = 3,
        backoff_seconds: float = 2.5,
        cache_dir: Path | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.timeout = httpx.Timeout(timeout_seconds, connect=min(10.0, timeout_seconds))
        self.max_retries = max_retries
        self.backoff = backoff_seconds
        self.robots = RobotsCache(user_agent, cache_dir=cache_dir)
        self._client = httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-IN,en;q=0.9",
            },
        )

    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get(
        self,
        url: str,
        *,
        respect_robots: bool = True,
        retries: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        if respect_robots and not self.robots.allowed(url, self):
            return FetchResult(
                url=url,
                status="robots_disallowed",
                error="Blocked by the site's robots.txt for this client",
                blocked_reason="robots.txt disallows automated access to this path",
            )

        attempts_allowed = (self.max_retries if retries is None else retries) + 1
        started = time.perf_counter()
        last: FetchResult | None = None

        for attempt in range(1, attempts_allowed + 1):
            try:
                response = self._client.get(url, headers=headers)
                elapsed = int((time.perf_counter() - started) * 1000)
                body = response.text[:6_000_000]
                blocked_reason = None
                if response.status_code in (401, 403, 429, 503):
                    lowered = body[:5000].lower()
                    marker = next((m for m in CHALLENGE_MARKERS if m in lowered), None)
                    if marker or response.status_code in (401, 403):
                        blocked_reason = (
                            f"Automated access refused by the site (HTTP {response.status_code}"
                            + (f", challenge marker: {marker!r}" if marker else "")
                            + "). Not bypassed."
                        )
                if response.status_code == 200:
                    # A 200 can still be an interstitial. Small + "just a moment"
                    # means a challenge page, which we report instead of parsing.
                    first_kb = body[:20000].lower()
                    if "just a moment" in first_kb and len(body) < 60000:
                        return FetchResult(
                            url=str(response.url), status="blocked", http_status=200, text=body,
                            latency_ms=elapsed, attempts=attempt,
                            error="HTTP 200 but the body is an anti-bot interstitial",
                            blocked_reason="The site served an anti-bot interstitial instead of the page. Not bypassed.",
                        )
                    return FetchResult(
                        url=str(response.url), status="ok", http_status=200, text=body,
                        headers={k.lower(): v for k, v in response.headers.items()},
                        latency_ms=elapsed, attempts=attempt,
                    )

                retryable = response.status_code in (408, 425, 429, 500, 502, 503, 504)
                last = FetchResult(
                    url=str(response.url),
                    status="blocked" if blocked_reason else "http_error",
                    http_status=response.status_code,
                    text=body,
                    latency_ms=elapsed,
                    attempts=attempt,
                    error=f"HTTP {response.status_code}",
                    blocked_reason=blocked_reason,
                )
                if not retryable or attempt == attempts_allowed:
                    return last
                retry_after = response.headers.get("retry-after")
                delay = self.backoff * attempt
                if retry_after and retry_after.isdigit():
                    delay = min(30.0, max(delay, float(retry_after)))
                time.sleep(delay + random.uniform(0, 0.4))
            except (httpx.TimeoutException,) as exc:
                last = FetchResult(
                    url=url, status="timeout", latency_ms=int((time.perf_counter() - started) * 1000),
                    attempts=attempt, error=f"Timeout after {self.timeout.read}s: {exc}",
                )
                if attempt == attempts_allowed:
                    return last
                time.sleep(self.backoff * attempt)
            except httpx.HTTPError as exc:
                last = FetchResult(
                    url=url, status="network_error", latency_ms=int((time.perf_counter() - started) * 1000),
                    attempts=attempt, error=f"{type(exc).__name__}: {exc}",
                )
                if attempt == attempts_allowed:
                    return last
                time.sleep(self.backoff * attempt)

        return last or FetchResult(url=url, status="network_error", error="Unknown fetch failure")
