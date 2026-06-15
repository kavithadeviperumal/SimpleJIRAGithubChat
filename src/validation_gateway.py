import logging
from dataclasses import dataclass
from typing import Optional
from src.jira_client import _resolve_jira_account_id
from src.github_client import _resolve_github_username
from src.exceptions import AmbiguousNameError

logger = logging.getLogger(__name__)

_JIRA_INTENTS = {'get_jira', 'get_activity'}
_GITHUB_INTENTS = {'get_commits', 'get_prs', 'get_activity'}


@dataclass
class ResolvedIdentity:
    display_name: str
    jira_account_id: Optional[str]
    github_login: Optional[str]


def validate_member(member_name, intent):
    check_jira = intent in _JIRA_INTENTS
    check_github = intent in _GITHUB_INTENTS

    jira_account_id = None
    github_login = None

    try:
        jira_account_id = _resolve_jira_account_id(member_name) if check_jira else None
    except AmbiguousNameError as e:
        candidates = ', '.join(e.candidates)
        return f"'{member_name}' matches multiple users in JIRA: {candidates}. Please use a more specific name.", set(), None

    try:
        github_login = _resolve_github_username(member_name) if check_github else None
    except AmbiguousNameError as e:
        candidates = ', '.join(e.candidates)
        return f"'{member_name}' matches multiple users in GitHub: {candidates}. Please use a more specific name.", set(), None

    jira_found = bool(jira_account_id)
    github_found = bool(github_login)

    if intent == 'get_activity':
        if not jira_found and not github_found:
            logger.warning('Validation failed: member not found in JIRA or GitHub')
            return (
                f"'{member_name}' was not found in our organization's JIRA or GitHub. "
                "Please check the name and try again."
            ), set(), None
    else:
        if check_jira and not jira_found:
            logger.warning('Validation failed: member not found in JIRA')
            return f"'{member_name}' was not found in JIRA. Please check the name and try again.", set(), None
        if check_github and not github_found:
            logger.warning('Validation failed: member not found in GitHub')
            return f"'{member_name}' was not found in GitHub. Please check the name and try again.", set(), None

    found = set()
    if jira_found:
        found.add('jira')
    if github_found:
        found.add('github')

    resolved = ResolvedIdentity(
        display_name=member_name,
        jira_account_id=jira_account_id,
        github_login=github_login,
    )
    logger.info('Validation passed: intent=%s found=%s', intent, found)
    return None, found, resolved
