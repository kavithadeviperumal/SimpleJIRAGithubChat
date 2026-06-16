import atexit
import logging
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, jsonify, request, send_from_directory
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.config import port, chat_api_key
from src.github_client import get_active_pull_requests, get_contributed_repos, get_recent_commits
from src.jira_client import get_issue_by_key, get_user_issues
from src.query_parser import parse_query
from src.validation_gateway import validate_member
from src.response_generator import (
    format_activity_response,
    format_commits_response,
    format_jira_response,
    format_prs_response,
    format_ticket_response,
)

logging.basicConfig(level=logging.INFO, force=True)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='../public', static_url_path='')
_limiter = Limiter(get_remote_address, app=app, storage_uri='memory://')
_executor = None
# Allowlist: only letters, spaces, apostrophes, hyphens, dots — blocks injection and LLM hallucinations
_NAME_RE = re.compile(r"^[A-Za-z\s'\-\.]{1,100}$")
_PRONOUNS = {'he', 'she', 'they', 'him', 'her', 'his', 'their', 'them', 'it'}


def _shutdown_executor():
    # Called on process exit (including Flask reloader restarts). wait=False avoids
    # blocking shutdown on any in-flight requests that are already being torn down.
    if _executor is not None:
        _executor.shutdown(wait=False)

# Ensures the thread pool is released whether the server stops normally or the
# debug reloader kills the child process mid-session.
atexit.register(_shutdown_executor)


@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/chat', methods=['POST'])
@_limiter.limit('10 per minute')
def chat():
    if chat_api_key:
        if request.headers.get('X-API-Key', '') != chat_api_key:
            return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json() or {}
    query = data.get('query', '').strip()

    if not query:
        return jsonify({'error': 'Query is required.'}), 400

    try:
        last_member = data.get('last_member')
        parsed = parse_query(query)
        intent = parsed.get('intent', 'unknown')
        extracted_name = parsed.get('member_name') or ''
        member_name = (None if extracted_name.lower() in _PRONOUNS else extracted_name) or last_member
        ticket_key = parsed.get('ticket_key')

        if intent == 'unknown':
            logger.warning('Unrecognized intent for query: %.200s', query)
            return jsonify({'response': "I'm not sure what you're asking. Try: \"What is John working on?\" or \"Show me Jane's recent commits.\""})

        if member_name and not _NAME_RE.match(member_name):
            return jsonify({'response': "I couldn't identify a valid team member name."})

        if not parsed.get('member_name') and member_name:
            logger.info('Using conversation context member')
        logger.info('Intent: %s | Member: %s | Ticket: %s', intent, member_name, ticket_key)

        # --- Ticket status lookup ---
        if intent == 'get_ticket':
            issue = get_issue_by_key(ticket_key)
            if issue is None:
                return jsonify({'response': f'Ticket {ticket_key} was not found. Check the key and try again.'})
            return jsonify({'response': format_ticket_response(issue), 'ticket': ticket_key})

        # --- Member-based queries ---
        if not member_name:
            return jsonify({'response': 'I couldn\'t identify a team member name. Try: "What is John working on?"'})

        error, found, resolved = validate_member(member_name, intent)
        if error:
            return jsonify({'response': error})

        # Ruthless optimization: each intent calls only the API it needs — no unnecessary
        # cross-system calls, saving rate limits and cutting response latency.
        # Extensibility: adding a new source (Slack, Confluence) only requires a new
        # client module, a new intent in the parser prompt, and one branch here.
        if intent == 'get_commits':
            commits = get_recent_commits(resolved.github_login)
            return jsonify({'response': format_commits_response(member_name, commits), 'member': member_name})

        elif intent == 'get_prs':
            prs = get_active_pull_requests(resolved.github_login)
            return jsonify({'response': format_prs_response(member_name, prs), 'member': member_name})

        elif intent == 'get_jira':
            issues = get_user_issues(resolved.jira_account_id)
            return jsonify({'response': format_jira_response(member_name, issues), 'member': member_name})

        elif intent == 'get_activity':
            # --- get_activity: fetch only from systems where user was found ---
            results = {'jira': None, 'commits': None, 'prs': None, 'repos': None}
            fetchers = []
            if '/jira' in found:
                fetchers.append(lambda: ('jira', get_user_issues(resolved.jira_account_id)))
            if 'github' in found:
                fetchers.append(lambda: ('commits', get_recent_commits(resolved.github_login)))
                fetchers.append(lambda: ('prs', get_active_pull_requests(resolved.github_login)))

            global _executor
            if _executor is None:
                _executor = ThreadPoolExecutor(max_workers=3)
            futures = [_executor.submit(fn) for fn in fetchers]
            repos_future = None
            for future in as_completed(futures):
                try:
                    key, result = future.result()
                    results[key] = result
                    if key == 'commits' and result:
                        repos_future = _executor.submit(get_contributed_repos, result)
                except Exception as e:
                    # Fault isolation: a failing worker (rate limit, timeout) is logged and
                    # skipped — remaining futures still collect, giving a partial response
                    # rather than crashing the whole request.
                    logger.error('Fetch failed: %s', e)

            if repos_future is not None:
                results['repos'] = repos_future.result()

            response = format_activity_response(
                member_name,
                results['jira'],
                results['commits'],
                results['prs'],
                results['repos'],
            )
            return jsonify({'response': response, 'member': member_name})

        else:
            logger.warning('Unrecognized intent reached dispatch: %s', intent)
            return jsonify({'response': "I'm not sure what you're asking. Try: \"What is John working on?\" or \"Show me Jane's recent commits.\""})

    except Exception as e:
        logger.error('Unhandled error: %s', e)
        return jsonify({'error': 'Something went wrong. Please try again.'}), 500


if __name__ == '__main__':
    app.run(port=port, debug=False)
