import logging
import requests
from datetime import datetime, timedelta
from config.config import github
from src.exceptions import AmbiguousNameError

logger = logging.getLogger(__name__)

_HEADERS = {
    'Authorization': f"Bearer {github['token']}",
    'Accept': 'application/vnd.github+json',
}
_github_login_cache = {}


def _resolve_github_username(display_name):
    if display_name in _github_login_cache:
        logger.info('Cache hit (GitHub login)')
        return _github_login_cache[display_name]

    org_qualifier = _scope_filter()
    for query in [
        f'fullname:"{display_name}"{org_qualifier}',
        f'{display_name} in:login{org_qualifier}',
    ]:
        response = requests.get(
            'https://api.github.com/search/users',
            headers=_HEADERS,
            params={'q': query, 'per_page': 5},
            timeout=10,
        )
        if not response.ok:
            logger.error('GitHub user search failed: %s %s', response.status_code, query)
            return None
        items = response.json().get('items', [])
        if items:
            break
    else:
        logger.warning('No GitHub user found for display name: %s', display_name)
        return None

    if len(items) > 1:
        exact = next((i for i in items if i['login'].lower() == display_name.lower()), None)
        if not exact:
            candidates = [i['login'] for i in items]
            logger.warning('Ambiguous GitHub name: %s → %s', display_name, candidates)
            raise AmbiguousNameError(candidates)
        item = exact
    else:
        item = items[0]

    login = item['login']
    _github_login_cache[display_name] = login
    logger.info('GitHub login resolved: %s → %s (matched query: %s)', display_name, login, query)
    return login


def _scope_filter(login=None):
    if github.get('org'):
        return f' org:{github["org"]}'
    target = login or github.get('username') or ''
    return f' user:{target}' if target else ''


def get_recent_commits(login):
    since = (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d')

    response = requests.get(
        'https://api.github.com/search/commits',
        headers={**_HEADERS, 'Accept': 'application/vnd.github.cloak-preview+json'},
        params={
            'q': f'author:{login} committer-date:>={since}',
            'sort': 'committer-date',
            'order': 'desc',
            'per_page': 10,
        },
        timeout=10,
    )
    if not response.ok:
        logger.error('GitHub commits failed: %s', response.status_code)
    response.raise_for_status()

    items = response.json().get('items', [])
    logger.info('GitHub commits returned %d results for "%s"', len(items), login)
    return [
        {
            'repo': item['repository']['full_name'],
            'message': item['commit']['message'].split('\n')[0],
            'date': item['commit']['committer']['date'],
        }
        for item in items
    ]


def get_active_pull_requests(login):
    since = (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d')
    response = requests.get(
        'https://api.github.com/search/issues',
        headers=_HEADERS,
        params={
            'q': f'is:pr author:{login} updated:>={since}',
            'sort': 'updated',
            'order': 'desc',
            'per_page': 10,
        },
        timeout=10,
    )
    if not response.ok:
        logger.error('GitHub PRs failed: %s', response.status_code)
    response.raise_for_status()

    prs = response.json().get('items', [])
    logger.info('GitHub PRs returned %d results', len(prs))
    return [
        {
            'title': pr['title'],
            'repo': pr['repository_url'].replace('https://api.github.com/repos/', ''),
            'state': pr['state'],
            'updated': pr['updated_at'],
            'url': pr['html_url'],
        }
        for pr in prs
    ]


def get_contributed_repos(commits: list) -> list:
    """
    Groups commits by repository and extracts the true maximum (latest) commit date.
    Operates completely in-memory with O(N) time complexity.
    """
    if not commits:
        return []

    latest_repo_dates = {}

    for commit in commits:
        repo_name = commit['repo']
        commit_date = commit['date']

        if repo_name not in latest_repo_dates or commit_date > latest_repo_dates[repo_name]:
            latest_repo_dates[repo_name] = commit_date

    return [
        {'repo': repo, 'last_commit': date}
        for repo, date in latest_repo_dates.items()
    ]
