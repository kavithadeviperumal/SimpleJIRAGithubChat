import json
import logging
import re
from openai import OpenAI
from config.config import openai as openai_config

logger = logging.getLogger(__name__)

_client = OpenAI(api_key=openai_config['api_key'])
_TICKET_KEY_RE = re.compile(r'\b([A-Z][A-Z0-9]+-\d+)\b', re.IGNORECASE)

_SYSTEM_PROMPT = (
    "Extract the intent and entities from a team activity query.\n"
    "Return ONLY valid JSON — no explanation, no markdown.\n\n"
    "Format: {\"intent\": \"<intent>\", \"member_name\": \"<name or null>\"}\n\n"
    "Intents:\n"
    "  get_activity  — general 'what is X working on' questions\n"
    "  get_commits   — questions specifically about commits\n"
    "  get_prs       — questions specifically about pull requests\n"
    "  get_jira      — questions specifically about JIRA tickets\n"
    "  unknown       — the query is not a recognizable team activity question\n\n"
    "member_name: extract only proper names (e.g. 'John', 'Sarah Chen'). "
    "Return null for pronouns (he, she, they, him, her, his), vague references, or when no name is present.\n\n"
    "If the query is gibberish, a greeting, or unrelated to team activity, return unknown."
)


def parse_query(query):
    # Fast path: detect ticket key with regex before calling AI
    ticket_match = _TICKET_KEY_RE.search(query)
    if ticket_match:
        return {'intent': 'get_ticket', 'member_name': None, 'ticket_key': ticket_match.group(1).upper()}

    response = _client.chat.completions.create(
        model='gpt-3.5-turbo',
        messages=[
            {'role': 'system', 'content': _SYSTEM_PROMPT},
            {'role': 'user', 'content': query},
        ],
        max_tokens=100,
        temperature=0,
        timeout=10,
    )

    _VALID_INTENTS = {'get_activity', 'get_commits', 'get_prs', 'get_jira', 'unknown'}
    try:
        parsed = json.loads(response.choices[0].message.content.strip())
        intent = parsed.get('intent', 'unknown')
        if intent not in _VALID_INTENTS:
            logger.warning('Unrecognized intent %r — treating as unknown', intent)
            intent = 'unknown'
        return {
            'intent': intent,
            'member_name': parsed.get('member_name'),
            'ticket_key': None,
        }
    except json.JSONDecodeError:
        raw = response.choices[0].message.content.strip()
        logger.warning('LLM returned unparseable JSON: %.200s', raw)
        return {'intent': 'unknown', 'member_name': None, 'ticket_key': None}
