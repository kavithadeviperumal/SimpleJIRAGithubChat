import pytest
from unittest.mock import patch
from src.main import app

SAMPLE_JIRA = [
    {
        'key': 'PROJ-101',
        'summary': 'Fix login bug',
        'status': 'In Progress',
        'priority': 'High',
        'updated': '2026-06-10T10:00:00.000+0000',
    }
]
SAMPLE_COMMITS = [
    {
        'repo': 'org/backend',
        'message': 'Fix auth issue',
        'date': '2026-06-10T09:00:00Z',
    }
]
SAMPLE_PRS = [
    {
        'title': 'Add OAuth support',
        'repo': 'org/backend',
        'state': 'open',
        'updated': '2026-06-10T08:00:00Z',
        'url': 'https://github.com/org/backend/pull/42',
    }
]


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


def post(client, query):
    return client.post('/chat', json={'query': query})


# Spec test cases 1-3: happy path for get_activity intent across different members
@pytest.mark.parametrize('member_name,query', [
    ('John', 'What is John working on these days?'),
    ('Sarah', 'Show me recent activity for Sarah'),
    ('Mike', 'What has Mike been working on this week?'),
])
@patch('src.main.get_active_pull_requests', return_value=SAMPLE_PRS)
@patch('src.main.get_recent_commits', return_value=SAMPLE_COMMITS)
@patch('src.main.get_user_issues', return_value=SAMPLE_JIRA)
@patch('src.main.validate_member', return_value=(None, {'jira', 'github'}))
@patch('src.main.parse_query')
def test_get_activity_happy_path(mock_parse, mock_validate, mock_jira, mock_commits, mock_prs, client, member_name, query):
    mock_parse.return_value = {'intent': 'get_activity', 'member_name': member_name}
    resp = post(client, query)
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'response' in data
    assert member_name in data['response']
    assert 'Activity summary' in data['response']
    assert 'JIRA' in data['response']
    assert 'Commits' in data['response']


# Spec test case 4: Handle case when user has no recent activity
@patch('src.main.get_active_pull_requests', return_value=[])
@patch('src.main.get_recent_commits', return_value=[])
@patch('src.main.get_user_issues', return_value=[])
@patch('src.main.validate_member', return_value=(None, {'jira', 'github'}))
@patch('src.main.parse_query', return_value={'intent': 'get_activity', 'member_name': 'John'})
def test_user_no_recent_activity(mock_parse, mock_validate, mock_jira, mock_commits, mock_prs, client):
    resp = post(client, 'What is John working on?')
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'response' in data
    assert 'No recent' in data['response']


# get_commits intent: returns recent commits for a member
@patch('src.main.get_recent_commits', return_value=SAMPLE_COMMITS)
@patch('src.main.validate_member', return_value=(None, {'github'}))
@patch('src.main.parse_query', return_value={'intent': 'get_commits', 'member_name': 'John'})
def test_get_commits(mock_parse, mock_validate, mock_commits, client):
    resp = post(client, 'Show me recent commits for John')
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'response' in data
    assert 'John' in data['response']
    assert 'Recent commits by' in data['response']
    assert 'org/backend' in data['response']


# get_prs intent: returns open pull requests for a member
@patch('src.main.get_active_pull_requests', return_value=SAMPLE_PRS)
@patch('src.main.validate_member', return_value=(None, {'github'}))
@patch('src.main.parse_query', return_value={'intent': 'get_prs', 'member_name': 'John'})
def test_get_prs(mock_parse, mock_validate, mock_prs, client):
    resp = post(client, 'Show open PRs for John')
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'response' in data
    assert 'John' in data['response']
    assert 'Open pull requests by' in data['response']
    assert 'Add OAuth support' in data['response']


# get_jira intent: returns JIRA tickets assigned to a member
@patch('src.main.get_user_issues', return_value=SAMPLE_JIRA)
@patch('src.main.validate_member', return_value=(None, {'jira'}))
@patch('src.main.parse_query', return_value={'intent': 'get_jira', 'member_name': 'John'})
def test_get_jira(mock_parse, mock_validate, mock_jira, client):
    resp = post(client, 'Show JIRA tickets for John')
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'response' in data
    assert 'John' in data['response']
    assert 'JIRA tickets assigned to' in data['response']
    assert 'PROJ-101' in data['response']


# Spec test case 5: Handle case when user is not found
@patch('src.main.validate_member', return_value=(
    "'Unknown' was not found in our organization's JIRA or GitHub. Please check the name and try again.",
    set()
))
@patch('src.main.parse_query', return_value={'intent': 'get_activity', 'member_name': 'Unknown'})
def test_user_not_found(mock_parse, mock_validate, client):
    resp = post(client, 'What is Unknown working on?')
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'response' in data
    assert 'not found' in data['response']
