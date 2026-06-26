"""tiny-http — Zero-dependency HTTP client for Python.

Single file. No dependencies. GET/POST/PUT/DELETE/PATCH with JSON,
streaming, retries, sessions, and rate limiting.
"""

import json
import urllib.request
import urllib.error
import urllib.parse
import socket
import time
import threading
from typing import Any, Callable, Dict, IO, List, Optional, Tuple, Union
from io import BytesIO

__version__ = "1.0.0"
__all__ = ["Client", "Request", "Response", "get", "post", "put", "delete", "patch"]


class Response:
    """HTTP response wrapper."""

    def __init__(
        self,
        status: int,
        body: bytes,
        headers: Dict[str, str],
        url: str,
        duration: float,
    ):
        self.status = status
        self._body = body
        self.headers = headers
        self.url = url
        self.duration = duration

    @property
    def text(self) -> str:
        """Decode body as UTF-8 text."""
        return self._body.decode("utf-8", errors="replace")

    @property
    def json(self) -> Any:
        """Parse body as JSON."""
        return json.loads(self.text)

    @property
    def content(self) -> bytes:
        """Raw response bytes."""
        return self._body

    @property
    def ok(self) -> bool:
        """True if status is 2xx."""
        return 200 <= self.status < 300

    def raise_for_status(self) -> None:
        """Raise HTTPError if status >= 400."""
        if self.status >= 400:
            raise urllib.error.HTTPError(
                self.url, self.status, f"HTTP {self.status}", self.headers, BytesIO(self._body)
            )

    def __repr__(self) -> str:
        return f"<Response [{self.status}] {len(self._body)} bytes in {self.duration:.3f}s>"


class RetryConfig:
    """Configure retry behavior."""

    def __init__(
        self,
        max_retries: int = 3,
        delay: float = 1.0,
        backoff: float = 2.0,
        max_delay: float = 30.0,
        status_forcelist: Tuple[int, ...] = (429, 500, 502, 503, 504),
    ):
        self.max_retries = max_retries
        self.delay = delay
        self.backoff = backoff
        self.max_delay = max_delay
        self.status_forcelist = status_forcelist

    def should_retry(self, status: int, attempt: int) -> bool:
        return attempt < self.max_retries and status in self.status_forcelist

    def delay_for(self, attempt: int) -> float:
        d = self.delay * (self.backoff ** attempt)
        return min(d, self.max_delay)


class RateLimiter:
    """Token bucket rate limiter for requests."""

    def __init__(self, rate: float = 10.0, burst: int = 5):
        self.rate = rate
        self.burst = burst
        self.tokens = burst
        self.last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: int = 1) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self.last
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.last = now
            if self.tokens >= tokens:
                self.tokens -= tokens
                return
            wait = (tokens - self.tokens) / self.rate
        time.sleep(max(0, wait))
        self.acquire(tokens)


class Client:
    """HTTP client with retries, sessions, cookies, and rate limiting."""

    def __init__(
        self,
        base_url: str = "",
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
        retries: Optional[RetryConfig] = None,
        rate_limiter: Optional[RateLimiter] = None,
        cookies: Optional[Dict[str, str]] = None,
        follow_redirects: bool = True,
    ):
        self.base_url = base_url.rstrip("/")
        self.headers = headers or {}
        self.timeout = timeout
        self.retries = retries or RetryConfig()
        self.rate_limiter = rate_limiter
        self.cookies = cookies or {}
        self.follow_redirects = follow_redirects
        self._stats = {"requests": 0, "errors": 0, "retries": 0}

    def _build_url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}/{path.lstrip('/')}"

    def _build_request(
        self,
        method: str,
        url: str,
        data: Any = None,
        json_data: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, str]] = None,
    ) -> urllib.request.Request:
        merged_headers = dict(self.headers)
        if headers:
            merged_headers.update(headers)

        # Add cookies
        if self.cookies:
            cookie_str = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
            merged_headers["Cookie"] = cookie_str

        if json_data is not None:
            body = json.dumps(json_data).encode("utf-8")
            merged_headers.setdefault("Content-Type", "application/json")
        elif data is not None:
            if isinstance(data, dict):
                body = urllib.parse.urlencode(data).encode("utf-8")
                merged_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
            elif isinstance(data, bytes):
                body = data
            else:
                body = str(data).encode("utf-8")
        else:
            body = None

        if params:
            sep = "&" if "?" in url else "?"
            url += sep + urllib.parse.urlencode(params)

        req = urllib.request.Request(
            url,
            data=body,
            headers=merged_headers,
            method=method,
        )
        return req

    def request(
        self,
        method: str,
        url: str,
        data: Any = None,
        json: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        stream: bool = False,
    ) -> Response:
        """Make an HTTP request with retries and rate limiting."""
        full_url = self._build_url(url)
        req = self._build_request(method, full_url, data, json, headers, params)
        timeout_val = timeout or self.timeout

        if self.rate_limiter:
            self.rate_limiter.acquire()

        attempt = 0
        start = time.monotonic()

        while True:
            try:
                ctx = urllib.request.urlopen(req, timeout=timeout_val)
                body = ctx.read()
                status = ctx.getcode() or 200
                resp_headers = dict(ctx.headers)

                # Extract cookies
                if "Set-Cookie" in resp_headers:
                    self._parse_cookie(resp_headers["Set-Cookie"])

                self._stats["requests"] += 1
                duration = time.monotonic() - start

                return Response(status, body, resp_headers, full_url, duration)

            except urllib.error.HTTPError as e:
                body = e.read() if hasattr(e, "read") else b""
                self._stats["errors"] += 1

                if self.retries.should_retry(e.code, attempt):
                    attempt += 1
                    self._stats["retries"] += 1
                    time.sleep(self.retries.delay_for(attempt))
                    continue

                duration = time.monotonic() - start
                return Response(e.code, body, dict(e.headers), full_url, duration)

            except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
                self._stats["errors"] += 1
                if attempt < self.retries.max_retries:
                    attempt += 1
                    self._stats["retries"] += 1
                    time.sleep(self.retries.delay_for(attempt))
                    continue
                raise

    def _parse_cookie(self, cookie_header: str) -> None:
        for cookie in cookie_header.split(","):
            parts = cookie.strip().split(";")[0].split("=")
            if len(parts) >= 2:
                self.cookies[parts[0].strip()] = parts[1].strip()

    def get(self, url: str, **kwargs) -> Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs) -> Response:
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs) -> Response:
        return self.request("DELETE", url, **kwargs)

    def patch(self, url: str, **kwargs) -> Response:
        return self.request("PATCH", url, **kwargs)

    def stream(self, url: str, method: str = "GET", **kwargs) -> bytes:
        """Yield response chunks for streaming."""
        # Note: urllib doesn't support true streaming well; this reads full response
        resp = self.request(method, url, **kwargs)
        yield resp.content

    def close(self) -> None:
        """Cleanup (no-op for urllib, but provided for API compatibility)."""
        pass

    def stats(self) -> dict:
        return dict(self._stats)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __repr__(self) -> str:
        return f"<Client base={self.base_url} requests={self._stats['requests']}>"


# Module-level convenience client
_default_client: Optional[Client] = None


def _get_default() -> Client:
    global _default_client
    if _default_client is None:
        _default_client = Client()
    return _default_client


def get(url: str, **kwargs) -> Response:
    return _get_default().get(url, **kwargs)


def post(url: str, **kwargs) -> Response:
    return _get_default().post(url, **kwargs)


def put(url: str, **kwargs) -> Response:
    return _get_default().put(url, **kwargs)


def delete(url: str, **kwargs) -> Response:
    return _get_default().delete(url, **kwargs)


def patch(url: str, **kwargs) -> Response:
    return _get_default().patch(url, **kwargs)
