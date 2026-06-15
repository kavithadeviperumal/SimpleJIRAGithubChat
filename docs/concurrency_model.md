# Concurrency Model

## Overview

This app has two layers of concurrency operating at different scopes:

| Layer | Mechanism | Scope |
|---|---|---|
| Between requests | Flask's threaded server | One thread per incoming request |
| Within a request | `ThreadPoolExecutor` | Parallel API calls inside `get_activity` |

---

## Layer 1: Between Requests — Flask Threads

Flask's built-in server has run with `threaded=True` by default since Flask 1.0. Each incoming request gets its own OS thread. Two users hitting `/chat` simultaneously do not queue — they run concurrently.

```python
app.run(port=3000, debug=False)
# threaded=True is implicit
```

**Why threads work here despite Python's GIL:**

The GIL (Global Interpreter Lock) prevents two Python threads from executing Python bytecode simultaneously. However, the GIL is *released* during I/O — specifically during network syscalls (`send`, `recv`). Since every request in this app spends most of its time waiting on JIRA, GitHub, and OpenAI, threads genuinely overlap their wait time. The GIL only blocks during CPU-bound Python execution, which is minimal here.

---

## Layer 2: Within a Request — ThreadPoolExecutor

The `get_activity` intent needs data from three sources: JIRA issues, GitHub commits, and GitHub PRs. Fetching them sequentially means total latency = `t_jira + t_commits + t_prs`. Fetching in parallel means total latency ≈ `max(t_jira, t_commits, t_prs)`.

```python
# main.py
_executor = ThreadPoolExecutor(max_workers=3)
futures = [_executor.submit(fn) for fn in fetchers]

for future in as_completed(futures):
    key, result = future.result()
    results[key] = result
    if key == 'commits' and result:
        repos_future = _executor.submit(get_contributed_repos, result)
```

**Chained future pattern:** `get_contributed_repos` is submitted inside the `as_completed` loop the moment commits land — it runs concurrently with still-in-flight JIRA and PR fetches, rather than after all three complete.

**Lazy initialisation:** `_executor` is `None` at startup and created on the first `get_activity` request. Other intents (`get_commits`, `get_prs`, `get_jira`) never use the executor — no point creating it at startup.

**Graceful shutdown:**
```python
atexit.register(_shutdown_executor)  # wait=False — don't block teardown
```
Fires on both normal server stop and Flask reloader child-process kills.

---

## The Gap: Shared Executor Under Concurrent Requests

The `_executor` is a global shared across all request threads. With 5 concurrent requests each submitting 3 tasks, you have 15 tasks competing for 3 worker slots. The executor queues the excess — no crash, but latency spikes under load.

For a small internal team this is acceptable. For production load, the right solution is async:

```
Current:  Flask + ThreadPoolExecutor  (threads, GIL, ~3 concurrent API calls)
Upgrade:  FastAPI + asyncio + httpx   (single thread, event loop, true non-blocking I/O)
```

---

## Multi-Worker Deployments (Gunicorn)

Flask's built-in server is not designed for production. You swap it for Gunicorn:

```bash
gunicorn -w 4 "src.main:app"
```

`-w 4` spawns 4 separate OS processes, each a full copy of the app. Rule of thumb: `2 × CPU cores + 1` workers.

**Why this app benefits from multiple workers:** Each `/chat` request can block for several seconds on I/O. With 1 worker, a second request queues. With 4 workers, 4 requests block on I/O simultaneously.

**Side effect on rate limiting:** Each worker has its own in-memory rate counter. With 4 workers and `10/minute` limit, effective limit per IP becomes `40/minute`. To enforce the limit correctly across workers, use a shared store:

```python
# Single process (current)
_limiter = Limiter(get_remote_address, app=app, storage_uri='memory://')

# Multi-worker
_limiter = Limiter(get_remote_address, app=app, storage_uri='redis://localhost:6379')
```

---

## Summary

```
Incoming request
  │
  ▼ Flask thread (one per request, GIL released during I/O)
  │
  ├── get_ticket / get_commits / get_prs / get_jira
  │     └── single API call, returns directly
  │
  └── get_activity
        └── ThreadPoolExecutor (max_workers=3)
              ├── JIRA issues fetch      ─┐
              ├── GitHub commits fetch    ├── overlap in time
              ├── GitHub PRs fetch       ─┘
              └── get_contributed_repos  ── starts as soon as commits land
```
