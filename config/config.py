import os
from dotenv import load_dotenv

load_dotenv()

_required = ['JIRA_BASE_URL', 'JIRA_EMAIL', 'JIRA_API_TOKEN', 'GITHUB_TOKEN', 'OPENAI_API_KEY']

for _key in _required:
    if not os.getenv(_key):
        raise EnvironmentError(f"Missing required environment variable: {_key}")

jira = {
    'base_url': os.getenv('JIRA_BASE_URL'),
    'email': os.getenv('JIRA_EMAIL'),
    'token': os.getenv('JIRA_API_TOKEN'),
}

github = {
    'token': os.getenv('GITHUB_TOKEN'),
    'org': os.getenv('GITHUB_ORG'),
    'username': os.getenv('GITHUB_USERNAME'),
}

openai = {
    'api_key': os.getenv('OPENAI_API_KEY'),
}

port = int(os.getenv('PORT', 3000))
chat_api_key = os.getenv('CHAT_API_KEY')
