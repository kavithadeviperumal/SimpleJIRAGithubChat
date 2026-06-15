# Query Parsing: Fast Path + Slow Path

## The Problem

User queries are free-form natural language:
- "What is John working on?"
- "Show me Sarah's pull requests"
- "What's the status of PROJ-123?"
- "What about her commits?" ← no name, relies on context

The app needs to extract two things: **intent** (what kind of data to fetch) and **member_name** (whose data). A regex alone can't handle position variation, possessives, or zero-name follow-ups. The LLM is the correct tool for semantic extraction — not an optimisation, but the right fit for the problem.

---

## Two Paths

```
User query
    │
    ▼
Does the query contain a JIRA ticket key pattern? (e.g. PROJ-123)
    │
    ├── YES → Fast path: return immediately, skip the LLM
    │
    └── NO  → Slow path: send to LLM, extract intent + member_name
```

---

## Fast Path — Regex

```python
_TICKET_KEY_RE = re.compile(r'\b([A-Z][A-Z0-9]+-\d+)\b')

ticket_match = _TICKET_KEY_RE.search(query)
if ticket_match:
    return {'intent': 'get_ticket', 'member_name': None, 'ticket_key': ticket_match.group(1)}
```

JIRA ticket keys have a rigid, deterministic structure (`PROJECT-123`). A regex is both faster and more reliable than an LLM for this — no ambiguity, no tokens consumed, no latency. The regex catches it; the LLM is never called.

**Security property:** The regex match result is already validated by definition — anything that matches `[A-Z][A-Z0-9]+-\d+` is a safe string to use in a URL path. No further validation needed.

---

## Slow Path — LLM

```python
_SYSTEM_PROMPT = (
    "Extract the intent and entities from a team activity query.\n"
    "Return ONLY valid JSON — no explanation, no markdown.\n\n"
    "Format: {\"intent\": \"<intent>\", \"member_name\": \"<name or null>\"}\n\n"
    "Intents:\n"
    "  get_activity  — general 'what is X working on' questions\n"
    "  get_commits   — questions specifically about commits\n"
    "  get_prs       — questions specifically about pull requests\n"
    "  get_jira      — questions specifically about JIRA tickets\n\n"
    "member_name: the person's full name as mentioned, or null"
)
```

Only runs when the fast path finds no ticket key. Extracts:
- `intent` — one of four values
- `member_name` — the person's name, or `null` for follow-up queries ("What about her PRs?")

`ticket_key` is intentionally absent from this prompt — see below.

---

## Why `ticket_key` Was Removed from the LLM Prompt

The original prompt included `ticket_key` as a third output field. This was dead code.

The fast path regex runs *before* the LLM. If the query contains a ticket key, execution returns immediately from the fast path — the LLM is never called. The slow path only runs when no ticket key was found. Therefore the LLM's `ticket_key` output was always `null`.

Including it in the prompt had two costs:
1. **Wasted tokens** — the LLM reasoned about a field it could never meaningfully populate
2. **Security risk** — if a prompt injection coerced the LLM to return a crafted `ticket_key`, that string went directly into a URL: `f"{jira_base_url}/rest/api/3/issue/{key}"` — path traversal risk

Removing it simplified the prompt and eliminated the attack surface entirely.

---

## Slow Path Return Contract

```python
try:
    parsed = json.loads(response.choices[0].message.content.strip())
    return {
        'intent': parsed.get('intent', 'get_activity'),
        'member_name': parsed.get('member_name'),
        'ticket_key': None,                           # always None — fast path handles this
    }
except json.JSONDecodeError:
    raw = response.choices[0].message.content.strip()
    logger.warning('LLM returned unparseable JSON: %.200s', raw)
    return {'intent': 'get_activity', 'member_name': None, 'ticket_key': None}
```

Key decisions:
- `ticket_key` is hardcoded to `None` — not read from the LLM response
- Uses `.get()` with defaults rather than mutating the dict (`setdefault`) — unexpected LLM fields can't bleed through
- `JSONDecodeError` logs the actual raw response before falling back — parse failures are visible in logs

---

## LLM as a Sanitization Boundary — Why It Fails

The LLM's job is semantic extraction, not input sanitization. A crafted query can coerce it to echo payloads verbatim:

```
Query: "What is John Smith\" org:evil working on?"
LLM extracts: member_name = 'John Smith" org:evil'
```

If that flows into GitHub search:
```python
f'author-name:"{member_name}" committer-date:>={since}'
# → author-name:"John Smith" org:evil committer-date:>=...
```

The `"` closes the quoted field and the injected modifiers become active search terms.

**The fix is not to clean the LLM's output at the call site.** The fix is an allowlist at the entry point in `main.py`, before the value is used anywhere:

```python
_NAME_RE = re.compile(r"^[A-Za-z\s'\-\.]{1,100}$")

if member_name and not _NAME_RE.match(member_name):
    return jsonify({'response': "I couldn't identify a valid team member name."}), 400
```

This runs once and protects all downstream uses — JIRA queries, GitHub queries, log messages, response formatting.

---

## Full Flow

```
User query: "What is Sarah's pull requests?"
    │
    ▼
_TICKET_KEY_RE.search(query) → no match
    │
    ▼
OpenAI gpt-3.5-turbo
    system: extract intent + member_name
    user:   "What is Sarah's pull requests?"
    →  {"intent": "get_prs", "member_name": "Sarah"}
    │
    ▼
slow path return:
    intent      = "get_prs"
    member_name = "Sarah"
    ticket_key  = None
    │
    ▼
main.py: _NAME_RE.match("Sarah") → valid
    │
    ▼
validate_member("Sarah", "get_prs") → check GitHub only
    │
    ▼
get_active_pull_requests("Sarah")
```
