# Team Activity Monitor

AI chatbot that answers "What is [member] working on?" by pulling live data from JIRA and GitHub.

## Setup

### 1. Create and activate a virtual environment
```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure environment
```bash
cp .env.example .env
```
Edit `.env` and fill in your credentials:

| Variable | Required | Description |
|---|---|---|
| `JIRA_BASE_URL` | Yes | Your Atlassian URL, e.g. `https://mycompany.atlassian.net` |
| `JIRA_EMAIL` | Yes | Your Atlassian account email |
| `JIRA_API_TOKEN` | Yes | Generate at https://id.atlassian.com/manage-profile/security/api-tokens |
| `GITHUB_TOKEN` | Yes | Classic PAT with `repo` and `read:user` scopes |
| `OPENAI_API_KEY` | Yes | API key from https://platform.openai.com/api-keys |
| `GITHUB_USERNAME` | Yes* | Your GitHub login (required for personal repos with no org) |
| `GITHUB_ORG` | No | GitHub org slug — overrides `GITHUB_USERNAME` when set |
| `CHAT_API_KEY` | No | Enables `X-API-Key` header auth on `/chat` if set |
| `PORT` | No | Server port (default: 3000) |

> \* Either `GITHUB_USERNAME` or `GITHUB_ORG` must be set to scope user search correctly.

### 4. Run the server
```bash
python src/main.py
```

Open http://localhost:3000

## Example Queries

| Intent | Example |
|---|---|
| General activity | "What is John working on?" |
| Commits only | "Show me Sarah's recent commits" |
| Pull requests only | "What PRs does Mike have open?" |
| JIRA only | "What JIRA tickets is Lisa working on?" |
| Ticket lookup | "What is the status of PROJ-123?" |
| Pronoun follow-up | "What is he working on?" *(uses previous member from conversation)* |

## Project Structure

```
├── config/config.py              # Reads .env, validates required vars, exports clean config
├── src/
│   ├── main.py                   # Flask server, /chat endpoint, intent routing
│   ├── query_parser.py           # OpenAI: extracts intent + member name from natural language
│   ├── validation_gateway.py     # Pre-flight check: resolves + confirms member exists before fetching
│   ├── jira_client.py            # JIRA REST API: assigned issues updated in last 7 days
│   ├── github_client.py          # GitHub REST API: recent commits + PRs updated in last 7 days
│   ├── response_generator.py     # Deterministic templates: formats JIRA + GitHub data into response
│   └── exceptions.py             # Shared exceptions (AmbiguousNameError)
└── public/
    ├── index.html                # Chat UI
    └── script.js                 # Frontend fetch logic
```

## How It Works

1. User submits a natural language question via the chat UI
2. `query_parser` makes a single OpenAI call to extract **intent** and **member name** as JSON
   - Fast-path regex detects JIRA ticket keys (e.g. `PROJ-123`) before the AI call
   - Pronouns (he, she, they) are not extracted as member names — the system falls back to the last resolved member from the conversation instead
   - Gibberish or off-topic queries return an `unknown` intent, which short-circuits immediately with a user-facing message — no validation or API calls made
3. `validation_gateway` resolves the member name to real JIRA account IDs and GitHub logins — scoped to your org or personal account. Returns an error if the member is not found or the name matches multiple users. Resolved IDs are passed directly to the JIRA and GitHub client functions for all intent paths
4. Intent routing calls only the APIs needed:
   - `get_activity` — fetches JIRA + GitHub in parallel (ThreadPoolExecutor)
   - `get_commits` / `get_prs` / `get_jira` — single targeted API call
   - `get_ticket` — single JIRA issue lookup by key
5. `response_generator` formats the data using deterministic templates — no second AI call
6. Response is displayed in the chat UI

Individual API failures are caught and isolated — a partial response is returned rather than an error.
