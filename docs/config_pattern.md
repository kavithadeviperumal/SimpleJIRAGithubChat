# Configuration Pattern: `.env` + `config.py`

## Why Both?

They solve different problems and should not be merged.

| | `.env` | `config.py` |
|---|---|---|
| **Responsibility** | Stores secret values | Defines what the app needs |
| **Who reads it** | `python-dotenv` at startup | Every module that needs config |
| **Changes per environment** | Yes (dev vs. prod) | No |
| **In version control** | Never | Yes |
| **Validates anything** | No | Yes |

Without `.env`: secrets end up hardcoded in source or require manual `export` commands before every run.

Without `config.py`: every module calls `os.getenv()` directly — no validation, no structure, missing vars discovered mid-request instead of at startup.

---

## How They Work Together

When `python src/main.py` runs, this is the exact execution sequence:

### Step 1 — `config.py` is imported by `main.py`
```python
from config.config import port, chat_api_key
```
Python executes `config.py` top to bottom.

### Step 2 — `load_dotenv()` populates `os.environ`
```python
load_dotenv()
```
`python-dotenv` reads `.env` line by line and calls `os.environ['KEY'] = 'value'` for each entry. The values now live in the process environment — identical to OS-level env vars set via `export`.

### Step 3 — Validation runs at startup
```python
_required = ['JIRA_BASE_URL', 'JIRA_EMAIL', 'JIRA_API_TOKEN', 'GITHUB_TOKEN', 'OPENAI_API_KEY']

for _key in _required:
    if not os.getenv(_key):
        raise EnvironmentError(f"Missing required environment variable: {_key}")
```
If anything is missing, the server exits immediately with a clear error — before serving a single request. This is "fail fast": better to crash at startup with a useful message than fail silently on the first user query.

### Step 4 — Structured dicts are built
```python
jira = {
    'base_url': os.getenv('JIRA_BASE_URL'),
    'email':    os.getenv('JIRA_EMAIL'),
    'token':    os.getenv('JIRA_API_TOKEN'),
}
```
`os.getenv()` reads from the environment that `load_dotenv()` just populated. Values are grouped by service rather than kept as a flat bag of strings.

### Step 5 — Client modules import the dicts
```python
# jira_client.py
from config.config import jira
_auth = (jira['email'], jira['token'])
```
`jira_client.py` never touches `os.environ` or `.env` directly. It uses the already-validated, already-structured dict.

---

## Data Flow

```
.env file
  │
  ▼ (python-dotenv load_dotenv)
os.environ  ←── also picks up any OS-level env vars
  │
  ▼ (os.getenv in config.py)
config.py  →  validates required keys
           →  builds structured dicts: jira{}, github{}, openai{}
  │
  ▼ (from config.config import ...)
jira_client.py
github_client.py
query_parser.py
main.py
```

The `.env` file and `os.environ` are never accessed past `config.py`. All other modules import only from `config.py`.

---

## Key Properties

**Single import point** — rename an env var and you change it in one place (`config.py`), not across every file that uses it.

**Startup validation** — missing config crashes the server immediately with a clear message, not silently when the first affected request comes in.

**Environment portability** — the same codebase runs locally (reads from `.env`), in CI (reads from CI secrets injected as env vars), and in production (reads from platform env vars) without any code changes. `load_dotenv()` is a no-op when the vars are already in the environment.
