# Security Hardening Guide

## 1. Never Run Flask with `debug=True` Outside Local Dev

```python
# Bad
app.run(port=3000, debug=True)

# Good
app.run(port=3000, debug=False)
```

`debug=True` enables Flask's interactive debugger. If an exception occurs, the browser gets a console where it can execute arbitrary Python — effectively remote code execution. It also:
- Exposes full stack traces with variable values to any client
- Auto-reloads the server on file changes (leaks file paths)
- Should never reach a shared or production environment

---

## 2. Input Validation: Allowlist Over Denylist

**Denylist** — remove known-bad characters:
```python
sanitized = user_input.replace('"', '')  # strips quotes to prevent breakout
```
This only fixes the known vector. Any character not on your denylist is still injectable.

**Allowlist** — permit only known-good characters:
```python
_NAME_RE = re.compile(r"^[A-Za-z\s'\-\.]{1,100}$")
if not _NAME_RE.match(member_name):
    return error
```
This blocks everything not explicitly permitted — current and future injection vectors alike.

**Rule:** For any field with a known shape (names, IDs, keys), use an allowlist regex. Validate once at the entry point, not at every downstream call site.

---

## 3. LLM Output Is Untrusted User Input

A large language model extracts structure from natural language — it does not sanitize it. A crafted query can coerce the LLM to echo injection payloads in its output:

```
Query:  "What is John Smith\" org:evil-org working on?"
LLM may extract member_name: 'John Smith" org:evil-org'
```

If that value flows into a GitHub search query:
```python
f'author-name:"{member_name}" committer-date:>={since}'
# becomes: author-name:"John Smith" org:evil-org committer-date:>=...
```

The LLM is a semantic parser, not a security boundary. Always validate LLM-returned values with the same rigor as direct user input before using them in queries, URLs, or API calls.

---

## 4. PII Must Not Appear in Logs

Member names, account IDs, and system logins are personally identifiable information. Logs are often:
- Stored in plaintext on disk
- Aggregated in central log systems (ELK, Datadog, CloudWatch)
- Accessible to people beyond the immediate team

**What to log:** counts, intents, status codes, durations.
**What not to log:** names, email addresses, account IDs, GitHub logins.

```python
# Bad
logger.info('Resolved "%s" → accountId %s', display_name, account_id)

# Good
logger.info('JIRA account resolved and cached')
```

---

## 5. API Error Response Bodies Must Not Be Logged

External API errors (JIRA, GitHub, OpenAI) can return response bodies containing names, email addresses, or other PII in error messages. Log only the HTTP status code.

```python
# Bad
logger.error('JIRA search %s — body: %s', response.status_code, response.text[:500])

# Good
logger.error('JIRA search failed: %s', response.status_code)
```

---

## 6. Set Timeouts on All External HTTP Calls

Without a timeout, a slow or unresponsive external service hangs the request thread indefinitely. With a thread pool of 3 workers, three hung requests block all future `get_activity` queries.

```python
# requests library
response = requests.get(url, timeout=10)

# OpenAI SDK
response = client.chat.completions.create(..., timeout=10)
```

`timeout=10` (seconds) is a reasonable default for JIRA/GitHub/OpenAI. Tune per-service based on observed p99 latency.

---

## 7. Rate Limit Endpoints That Fan Out to External APIs

`/chat` triggers up to 4 external API calls per request (JIRA user search, JIRA issues, GitHub commits, GitHub PRs). Without rate limiting:
- A single client can exhaust JIRA/GitHub rate limits for the whole team
- Parallel requests accumulate threads beyond the executor pool
- No protection against automated abuse

```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

_limiter = Limiter(get_remote_address, app=app, storage_uri='memory://')

@app.route('/chat', methods=['POST'])
@_limiter.limit('10 per minute')
def chat():
    ...
```

**Storage note:** `storage_uri='memory://'` stores counters in-process. Correct for a single-process deployment. In multi-worker deployments (Gunicorn `-w N`), each worker has its own counter — effective limit becomes `10 × N/minute`. Use `storage_uri='redis://...'` for shared state across workers.

---

## 8. Gate Optional Auth With an Env Var

A hard-coded auth check breaks existing integrations immediately. An env-var-gated check is backward compatible — no effect when the var is unset, activates when set.

```python
# config.py
chat_api_key = os.getenv('CHAT_API_KEY')  # optional — None if not set

# main.py
if chat_api_key:
    if request.headers.get('X-API-Key', '') != chat_api_key:
        return jsonify({'error': 'Unauthorized'}), 401
```

To enable: add `CHAT_API_KEY=some-secret` to `.env` and pass `X-API-Key: some-secret` from the client. To disable: remove the env var.

---

## 9. Surface Errors in Except Blocks — Log the Actual Content

A bare except that silently returns defaults makes failures invisible:

```python
# Bad — JSONDecodeError disappears silently
except json.JSONDecodeError:
    return defaults

# Good — failure is visible in logs
except json.JSONDecodeError:
    raw = response.choices[0].message.content.strip()
    logger.warning('LLM returned unparseable JSON: %.200s', raw)
    return defaults
```

`%.200s` truncates at 200 characters — enough to diagnose the problem (markdown wrapper, rate limit message, model error) without flooding the log.

Also remove dead exception types: `except (json.JSONDecodeError, KeyError)` is wrong when using `.get()` — `.get()` never raises `KeyError`. Dead clauses suggest the code wasn't fully reasoned through.
