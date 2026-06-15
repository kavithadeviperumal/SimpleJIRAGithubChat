# Team Activity Monitor — Architecture Evolution & Learnings

## Original Design Flow
```
User query
  → regex extract member name (caps pattern)
  → OpenAI fallback if regex fails               ← AI call #1
  → fetch ALL: JIRA issues + commits + PRs (parallel)
  → OpenAI synthesize conversational response    ← AI call #2
  → display
```

## Final Design Flow
```
User query
  → regex fast-path: detect JIRA ticket key (e.g. FULFIL-27) → get_ticket (no LLM)
  → OpenAI: extract intent + member_name as JSON              ← AI call #1 (only call)
      intents: get_activity | get_commits | get_prs | get_jira | unknown
      member_name: proper names only — pronouns (he/she/they) → null → fall back to last_member
      unknown → early user-facing message returned, no API calls made
  → allowlist validation: _NAME_RE blocks injection / LLM hallucinations
  → validate_member(name, intent) → resolves accountId + GitHub login
      returns (error, found_set, ResolvedIdentity(display_name, jira_account_id, github_login))
      AmbiguousNameError → surfaced as user-facing "matches multiple users" message
  → JIRA and GitHub client functions receive resolved IDs directly from ResolvedIdentity —
      no re-resolution inside the functions themselves
  → route by intent (explicit if/elif/else — no implicit fallthrough):
      get_ticket   → GET /rest/api/3/issue/{key}; 404 → user-facing "not found" message (no member needed)
      get_commits  → GitHub commits only
      get_prs      → GitHub PRs only
      get_jira     → JIRA assigned issues
      get_activity → fetch only from systems where member was found (ThreadPoolExecutor, max_workers=3)
                     repos derived in-memory from commits (O(N), no extra API call)
      else         → unrecognized intent → user-facing message, logged as warning
  → deterministic template formats the response (no AI)
  → display
```

**Why this is better:** One AI call instead of two. `get_ticket` skips the LLM entirely via regex. No hallucination risk in output. Only hits APIs actually needed per intent. Partial results for `get_activity` when user exists in only one system. Faster, cheaper, predictable.

---

## Module Map
```
src/
  main.py              — Flask app, /chat route, rate limiter, thread pool, input validation
  query_parser.py      — regex fast-path + OpenAI intent extraction
  validation_gateway.py — resolves member in JIRA/GitHub; returns (error, found_set, ResolvedIdentity)
  jira_client.py       — JIRA REST API v3: user resolution, issue search, single-ticket fetch
  github_client.py     — GitHub Search API: user resolution, commits, PRs, repo derivation
  response_generator.py — deterministic templates for all 5 response types
  exceptions.py        — AmbiguousNameError(candidates)

config/
  config.py            — single import point for all settings (reads from .env)

public/
  index.html           — chat UI with suggestion chips and empty state
  script.js            — fetch /chat, pass last_member context, thinking indicator
```

---

## Bugs Fixed & What Caused Them

### 1. Send button unclickable
- **Cause:** Flask's default `static_url_path` is `/static/`, so `script.js` was served at `/static/script.js`. The HTML referenced `<script src="script.js">` which requested `/script.js` → 404 → JS never loaded → `sendQuery` undefined → button did nothing silently.
- **Fix:** `Flask(__name__, static_folder='../public', static_url_path='')` — serves public folder at root.

### 2. JIRA 410 Gone on every endpoint
- **Cause:** Both `/rest/api/2/search` and `/rest/api/3/search` have been deprecated and removed by Atlassian.
- **Fix:** Migrate to `POST /rest/api/3/search/jql` with JSON body `{jql, fields, maxResults}`. The old endpoints used GET with query params; the new one is POST with JSON.
- **Learning:** Always log response body on non-2xx, not just status code. The body had the exact migration message.

### 3. JIRA returning 0 results despite 200
- **Cause:** JQL `assignee = "Display Name"` doesn't work in Jira Cloud REST API v3. Requires accountId.
- **Fix:** Added `_resolve_account_id(display_name)` which calls `GET /rest/api/3/user/search?query={name}` first, then uses the returned `accountId` in JQL.

### 4. GitHub returning hallucinated results
- **Cause:** `author:{username}` in GitHub search uses GitHub login handle, not display name. "Kavithadevi Perumal" is not a valid GitHub handle → matched random public repos.
- **Fix for commits:** Switched to `author:{login}` after resolving the login via `_resolve_github_username`.
- **Fix for PRs:** `_resolve_github_username` tries `fullname:"{name}"` first, then `{name} in:login` as fallback — two-pass search.

### 5. GitHub org scoping
- **Context:** GitHub token is personal, not a KSOM org token.
- **Fix:** `_scope_filter()` appends `org:{org}` when `GITHUB_ORG` is set. When absent, falls back to `user:{GITHUB_USERNAME}` if set, otherwise searches globally.

### 6. Ambiguous name resolution
- **Cause:** Generic names (e.g. "John") can match multiple JIRA or GitHub users, causing wrong data to be returned silently.
- **Fix:** `_resolve_account_id` and `_resolve_github_username` both raise `AmbiguousNameError(candidates)` when multiple users match and no exact-match by display/login name exists. `validate_member` catches this and returns a user-facing message listing the candidates.

### 7. get_contributed_repos as extra API call
- **Cause:** Original design made a separate GitHub API call to fetch repos.
- **Fix:** `get_contributed_repos(commits)` now groups the already-fetched commits by repo in-memory (O(N)) — no extra network call.

---

## Key Design Decisions

### Intent-based routing over catch-all fetching
"What is Balu working on?" maps to `get_activity` (fetch everything needed). Targeted queries like "Show me Balu's PRs" map to `get_prs` (single API call). `get_ticket` bypasses the LLM entirely — regex detects the key before the AI call is made.

### Partial results for get_activity
`validate_member` returns a `found` set: `{'jira'}`, `{'github'}`, or `{'jira', 'github'}`. `get_activity` only fetches from systems where the user was found. A user who exists in JIRA but not GitHub gets a JIRA-only summary without an error.

### Deterministic templates over AI synthesis
Response generation moved from OpenAI to hand-written templates in `response_generator.py`. Structured data (tickets, commits, PRs) doesn't benefit from AI narration — templates are faster, predictable, and can't hallucinate. Templates now include time tracking fields: estimate, timespent, duedate.

### ResolvedIdentity — explicit ID passing
`validate_member` resolves both IDs (JIRA accountId, GitHub login) and returns them in a `ResolvedIdentity` dataclass alongside `found_set`. All JIRA and GitHub client functions receive the resolved ID directly — `get_user_issues(account_id)`, `get_recent_commits(login)`, `get_active_pull_requests(login)` — rather than re-resolving from the display name. This applies across all intents, not just `get_activity`. The `_resolve_*` functions are now strictly internal to the gateway.

This eliminates hidden coupling: previously, client functions depended on the module-level cache being warm without declaring that dependency. Now the data flow is explicit.

### JIRA account ID resolution pattern
Same pattern as OAuth/LDAP: resolve human-readable name → internal ID → use ID for queries. Mirrors `_resolve_github_username`. Both cache results in module-level dicts (cross-request benefit on same process).

### Security hardening layer in main.py
- `_NAME_RE = r"^[A-Za-z\s'\-\.]{1,100}$"` — allowlist on extracted member name before any API call
- `flask_limiter` — 10 requests/minute per IP
- Optional `X-API-Key` header check — enabled when `CHAT_API_KEY` env var is set
- LLM output treated as untrusted: intent validated against `_VALID_INTENTS`; `unknown` intent triggers an early user-facing return before any validation or API call is made

### Thread pool lifecycle
`_executor` is lazy-initialized on first `get_activity` request (avoids creating threads if never used). `atexit.register(_shutdown_executor)` ensures clean teardown on both normal exit and Flask debug reloader kills. `repos_future` is submitted after commits return so repo derivation can overlap with PR fetch.

---

## Spec Coverage (final state)
| Requirement | Status |
|---|---|
| JIRA: assigned issues | Done |
| JIRA: issue status + recent updates | Done (status/priority/updated in every issue) |
| JIRA: time tracking fields | Done (estimate, timespent, duedate in responses) |
| JIRA: single ticket lookup | Done (get_ticket intent, full field set incl. assignee) |
| GitHub: recent commits | Done |
| GitHub: active pull requests | Done |
| GitHub: repos contributed to | Done (derived in-memory from commits, O(N)) |
| Chat interface | Done (suggestion chips, empty state, thinking indicator) |
| AI response generation | Done (OpenAI for intent extraction only; templates for output) |
| Error handling | Done (AmbiguousNameError surfaced, partial results, graceful messages) |

## Bonus Points Achieved (from spec)
- Multiple question formats (5 intents, `get_ticket` via regex fast-path)
- Priority levels and time tracking in JIRA responses
- Concurrent requests (ThreadPoolExecutor, max_workers=3, lazy init, atexit cleanup)
- Partial results: user found in one system still gets a useful response
- Ambiguous name detection with candidate list surfaced to user
- Validation gateway: sole gate for member resolution; returns `(error, found_set, ResolvedIdentity)` — resolved IDs passed directly to JIRA and GitHub client functions across all intents
- Account ID and GitHub login caching (module-level dicts)
- Conversation context: frontend stores `lastMember`, passed as `last_member` on follow-up queries
- Security: rate limiting, optional API key auth, input allowlist, LLM output validation

---

## Future Optimizations

### Parallelize validation gateway lookups
`validate_member()` currently calls `_resolve_account_id` and `_resolve_github_username` sequentially. Since both are independent network calls, they could run in parallel via `ThreadPoolExecutor(max_workers=2)`, cutting validation latency roughly in half on a cache miss. Not implemented because the cached path is already instant and the added complexity isn't justified for this sprint.

### Replace ThreadPoolExecutor with asyncio + aiohttp
`ThreadPoolExecutor` gives effective I/O concurrency because the GIL is released during network waits. However, there is a small OS scheduling gap between when one thread releases the GIL and when another acquires it (context switch cost, typically 1–10µs). `asyncio` with `aiohttp` eliminates this entirely — single-threaded cooperative multitasking with explicit `await` yield points, no context switch overhead. Preferred for high-throughput or latency-sensitive production workloads.

### Pre-warm member roster at startup
Currently, member resolution (JIRA accountId, GitHub login) happens on first query and is cached for the process lifetime. A startup job could pre-fetch all org members from `/orgs/{org}/members` and `/rest/api/3/users/search` to prime the cache before any user query arrives, eliminating first-query latency entirely.

### Persistent cache
Module-level dicts are in-process only — cleared on every server restart. Replacing them with Redis or a lightweight on-disk store (e.g. `shelve`) would preserve resolution cache across restarts and support multi-worker deployments.
