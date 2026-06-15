# API Issues Encountered

Real issues hit during development, with root cause and fix. Useful for Q&A prep and future integrations.

---

## JIRA

### 1. `/search` endpoint returns 410 Gone
- **Symptom:** Both `GET /rest/api/2/search` and `GET /rest/api/3/search` return 410.
- **Root cause:** Atlassian deprecated both endpoints in JIRA Cloud.
- **Fix:** `POST /rest/api/3/search/jql` with JSON body `{"jql": "...", "fields": [...]}`.
- **Lesson:** Log the response body on non-2xx — the body had the exact migration message.

### 2. JQL `assignee = "Display Name"` returns 0 results despite 200
- **Symptom:** Query succeeds but returns empty issue list.
- **Root cause:** JIRA Cloud v3 does not accept display names in JQL assignee filters. Requires `accountId`.
- **Fix:** Resolve display name → accountId first via `GET /rest/api/3/user/search?query={name}`, then use `assignee = "{accountId}"` in JQL.

---

## GitHub

### 3. Fine-grained PAT returns 0 results from `/search/commits`
- **Symptom:** Commit search returns 200 with empty array even when commits exist and repo permissions are set correctly.
- **Root cause:** GitHub's `/search/commits` API has a known incompatibility with fine-grained tokens. Fine-grained tokens are repo-scoped and lack the cross-boundary access the search index requires.
- **Fix:** Use a classic PAT with `repo` scope. Fine-grained tokens work for direct repo API calls but not for the search API.

### 4. Global `fullname:` user search resolves to wrong person
- **Symptom:** `fullname:"Sarah"` resolved to Sarah Drasner (prominent public GitHub user), not the org member named Sarah.
- **Root cause:** GitHub search ranks results by prominence globally — the most followed/active public user wins.
- **Fix:** Scope the user search with `org:{org}` when an org is set, or `user:{login}` for personal accounts. Never run user resolution against global GitHub.

### 5. `author:{display_name}` in commit search treats display name as a GitHub login
- **Symptom:** Commit search returned results from random public repos (e.g., `bad-apple-git`, commits dated year 8513).
- **Root cause:** `author:` in the search API matches against GitHub login handles, not display names. Passing a display name matches unrelated public users who happen to have a similar handle.
- **Fix:** Resolve the GitHub login first via user search, then use `author:{login}`.

### 6. `GITHUB_ORG` set to a personal account name breaks commit search
- **Symptom:** Setting `GITHUB_ORG=kavithadeviperumal` returned 0 commits.
- **Root cause:** `org:{name}` only matches GitHub organization repos. Personal user repos are excluded from `org:` queries.
- **Fix:** Use `org:{org}` only for real GitHub orgs. For personal accounts, use `user:{login}`. The `_scope_filter()` helper handles this automatically based on which env var is set.

### 7. PR search `user:{login}` filter too restrictive
- **Symptom:** PRs opened against repos not owned by the user were missing from results.
- **Root cause:** `is:pr author:{login} is:open user:{login}` scopes results to repos *owned* by the user — misses PRs opened against any other repo (e.g., a team repo).
- **Fix:** Remove `user:` from PR search. `is:pr author:{login}` finds all PRs authored by the user regardless of target repo.

### 8. `is:open` filters out all PRs for direct-to-main workflows
- **Symptom:** PR search returned 0 results even though the user had recent GitHub activity.
- **Root cause:** Direct-to-main commit workflow means no open PRs exist at any given time. `is:open` always returns empty.
- **Fix:** Replace `is:open` with `updated:>={since}` — catches both open and recently merged PRs within the time window.
