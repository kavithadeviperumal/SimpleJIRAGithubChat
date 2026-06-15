import logging
import requests
from config.config import jira
from src.exceptions import AmbiguousNameError

logger = logging.getLogger(__name__)

_auth = (jira['email'], jira['token'])
_headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
_account_id_cache = {}


def _resolve_jira_account_id(display_name):
    if display_name in _account_id_cache:
        logger.info('Cache hit (JIRA account)')
        return _account_id_cache[display_name]

    url = f"{jira['base_url']}/rest/api/3/user/search"
    response = requests.get(
        url,
        auth=_auth,
        headers=_headers,
        params={'query': display_name, 'maxResults': 5},
        timeout=10,
    )
    if not response.ok:
        logger.error('JIRA user search failed: %s', response.status_code)
        return None

    users = response.json()
    if not users:
        logger.warning('No JIRA user found')
        return None

    if len(users) > 1:
        exact = next((u for u in users if u.get('displayName', '').lower() == display_name.lower()), None)
        if not exact:
            candidates = [u.get('displayName', u['accountId']) for u in users]
            logger.warning('Ambiguous JIRA name: %s → %s', display_name, candidates)
            raise AmbiguousNameError(candidates)
        user = exact
    else:
        user = users[0]

    account_id = user['accountId']
    resolved_name = user.get('displayName', 'unknown')
    _account_id_cache[display_name] = account_id
    logger.info('JIRA account resolved: %s → %s (%s)', display_name, resolved_name, account_id)
    return account_id


def get_issue_by_key(key):
    response = requests.get(
        f"{jira['base_url']}/rest/api/3/issue/{key}",
        auth=_auth,
        headers=_headers,
        params={'fields': 'summary,status,priority,updated,assignee,description,timeoriginalestimate,timespent,duedate'},
        timeout=10,
    )
    if response.status_code == 404:
        logger.warning('JIRA ticket not found: %s', key)
        return None
    if not response.ok:
        logger.error('JIRA issue fetch failed: %s', response.status_code)
        response.raise_for_status()

    fields = response.json()['fields']
    assignee = (fields.get('assignee') or {}).get('displayName', 'Unassigned')
    return {
        'key': key,
        'summary': fields['summary'],
        'status': fields['status']['name'],
        'priority': (fields.get('priority') or {}).get('name', 'None'),
        'assignee': assignee,
        'updated': fields['updated'],
        'estimate': fields.get('timeoriginalestimate'),
        'timespent': fields.get('timespent'),
        'duedate': fields.get('duedate'),
    }


def get_user_issues(account_id):
    jql = f'assignee = "{account_id}" AND updated >= -7d ORDER BY updated DESC'

    response = requests.post(
        f"{jira['base_url']}/rest/api/3/search/jql",
        auth=_auth,
        headers=_headers,
        json={
            'jql': jql,
            'fields': ['summary', 'status', 'priority', 'updated', 'timeoriginalestimate', 'timespent', 'duedate'],
            'maxResults': 10,
        },
        timeout=10,
    )
    if not response.ok:
        logger.error('JIRA search failed: %s', response.status_code)
    response.raise_for_status()

    data = response.json()
    logger.info('JIRA returned %d issues', len(data.get('issues', [])))
    return [
        {
            'key': issue['key'],
            'summary': issue['fields']['summary'],
            'status': issue['fields']['status']['name'],
            'priority': (issue['fields'].get('priority') or {}).get('name', 'None'),
            'updated': issue['fields']['updated'],
            'estimate': issue['fields'].get('timeoriginalestimate'),
            'timespent': issue['fields'].get('timespent'),
            'duedate': issue['fields'].get('duedate'),
        }
        for issue in data.get('issues', [])
    ]
