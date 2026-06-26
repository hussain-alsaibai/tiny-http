# tiny-http

**Zero-dependency HTTP client for Python.**

Like `requests`, but in one file. No external dependencies — just `import` and request.

## Features

| Feature | Description |
|---------|-------------|
| **HTTP Methods** | GET, POST, PUT, DELETE, PATCH |
| **JSON** | Native `.json()` method on responses |
| **Retries** | Automatic retry with exponential backoff |
| **Rate Limiting** | Token bucket for controlled request rate |
| **Sessions** | Persistent headers, cookies across requests |
| **Query Params** | Automatic URL encoding |
| **Timeout** | Per-request and default timeout |
| **Stats** | Track requests, errors, retries |
| **Zero Deps** | Pure Python stdlib only |

## Install

```bash
pip install tiny-http
```

Or copy `tiny_http.py` — it's a single file.

## Quick Start

```python
from tiny_http import get, post

# GET
resp = get("https://api.example.com/users")
print(resp.json())

# POST with JSON
resp = post("https://api.example.com/users", json={"name": "Alice"})
print(resp.status)  # 201
```

## Client Session

```python
from tiny_http import Client

with Client(
    base_url="https://api.example.com",
    headers={"Authorization": "Bearer secret123"},
    timeout=10.0,
) as c:
    # All requests share base_url, headers, and cookies
    resp = c.get("/users")
    resp = c.post("/users", json={"name": "Bob"})
    resp = c.delete("/users/42")
```

## Retries

```python
from tiny_http import Client, RetryConfig

retry = RetryConfig(
    max_retries=5,
    delay=1.0,
    backoff=2.0,
    status_forcelist=(429, 500, 502, 503, 504),
)

with Client(retries=retry) as c:
    resp = c.get("https://unreliable.com/data")
    # Auto-retries on 5xx with backoff
```

## Rate Limiting

```python
from tiny_http import Client, RateLimiter

limiter = RateLimiter(rate=5.0, burst=3)  # 5 requests/sec

with Client(rate_limiter=limiter) as c:
    for url in urls:
        c.get(url)  # Auto-throttled
```

## Error Handling

```python
resp = get("https://api.example.com/data")

if resp.status == 404:
    print("Not found")
elif resp.status == 429:
    print("Rate limited")
elif resp.ok:
    print(resp.json())
else:
    resp.raise_for_status()  # Raises on 4xx/5xx
```

## Query Parameters

```python
resp = get("https://api.example.com/search", params={
    "q": "python",
    "limit": 10,
    "sort": "relevance"
})
# Requests: https://api.example.com/search?q=python&limit=10&sort=relevance
```

## Stats

```python
c = Client()
# ... make requests ...
print(c.stats())
# {'requests': 15, 'errors': 2, 'retries': 5}
```

## API

### Client Methods

| Method | Description |
|--------|-------------|
| `get(url, **kwargs)` | GET request |
| `post(url, **kwargs)` | POST request |
| `put(url, **kwargs)` | PUT request |
| `delete(url, **kwargs)` | DELETE request |
| `patch(url, **kwargs)` | PATCH request |

### Response Properties

| Property | Description |
|----------|-------------|
| `.status` | HTTP status code |
| `.text` | Decoded body as string |
| `.json()` | Parsed JSON |
| `.content` | Raw bytes |
| `.ok` | True if 2xx |
| `.duration` | Request time in seconds |
| `.raise_for_status()` | Raise on 4xx/5xx |

## License

MIT
