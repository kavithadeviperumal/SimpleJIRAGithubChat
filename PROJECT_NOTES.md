# Team Activity Monitor — Project Notes

Assignment from Autonomize: build a Team Activity Monitor chatbot as a rapid prototyping exercise.

**Why:** Evaluating rapid prototyping skills, API integration, and problem-solving. Demo scheduled 2026-06-12.

**Stack:**
- Backend: Python + Flask
- AI: OpenAI gpt-3.5-turbo — intent/entity extraction only (response generation is now template-based)
- APIs: JIRA REST API v3 + GitHub REST API
- Frontend: Vanilla HTML/CSS/JS chat interface
- Config: `.env` (secrets) + `config/config.py` (single validated import point)

**Final architecture (as of 2026-06-11):**
- Single AI call per query: extracts intent + member_name + ticket_key as JSON
- Intents: get_activity, get_commits, get_prs, get_jira, get_ticket
- Routing in main.py: each intent calls only the needed API(s)
- Responses: deterministic templates in response_generator.py (no AI synthesis)
- get_activity (catch-all): fetches JIRA + commits + PRs in parallel via ThreadPoolExecutor

**JIRA integration notes:**
- Endpoint: POST /rest/api/3/search/jql (both v2/search and v3/search are 410 Gone — deprecated)
- Assignee search requires accountId, not display name → _resolve_account_id() calls /rest/api/3/user/search first
- Single ticket lookup: GET /rest/api/3/issue/{key}

**GitHub integration notes:**
- Commits: author-name:"{display name}" works without GitHub handle
- PRs: requires GitHub login → _resolve_github_username() calls /search/users?q=fullname:"{name}"
- Optional GITHUB_ORG in .env scopes searches to org; absent = global search
- GitHub token is personal account, not KSOM org

**Entry point:** `python src/main.py` from project root. Flask runs on port 3000 with debug=True (auto-reload on file save).

**See also:** ARCHITECTURE.md for full design flow changes, bugs fixed, and learnings.
