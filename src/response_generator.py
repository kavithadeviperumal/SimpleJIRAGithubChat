def _no_data(member_name, source):
    return f"No recent {source} activity found for {member_name} in the last 7 days."


def _format_estimate(seconds):
    if not seconds:
        return None
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours and minutes:
        return f"{hours}h {minutes}m"
    return f"{hours}h" if hours else f"{minutes}m"


def format_ticket_response(issue):
    est = _format_estimate(issue.get('estimate'))
    spent = _format_estimate(issue.get('timespent'))
    est_line = f"\n  Estimate:     {est}" if est else ""
    spent_line = f"\n  Time spent:   {spent}" if spent else ""
    due_line = f"\n  Due date:     {issue['duedate']}" if issue.get('duedate') else ""
    return (
        f"{issue['key']}: {issue['summary']}\n"
        f"  Status:       {issue['status']}\n"
        f"  Priority:     {issue['priority']}\n"
        f"  Assignee:     {issue['assignee']}\n"
        f"  Last updated: {issue['updated'][:10]}"
        f"{est_line}{spent_line}{due_line}"
    )


def format_jira_response(member_name, jira_issues):
    if not jira_issues:
        return _no_data(member_name, 'JIRA')

    lines = [f"JIRA tickets assigned to {member_name}:\n"]
    for issue in jira_issues:
        est = _format_estimate(issue.get('estimate'))
        spent = _format_estimate(issue.get('timespent'))
        meta = f"Priority: {issue['priority']}"
        if est:
            meta += f" | Est: {est}"
        if spent:
            meta += f" | Spent: {spent}"
        if issue.get('duedate'):
            meta += f" | Due: {issue['duedate']}"
        lines.append(
            f"  {issue['key']} [{issue['status']}] {issue['summary']}\n"
            f"    {meta} | Updated: {issue['updated'][:10]}"
        )
    return '\n'.join(lines)


def format_commits_response(member_name, commits):
    if not commits:
        return _no_data(member_name, 'commit')

    lines = [f"Recent commits by {member_name}:\n"]
    for c in commits:
        lines.append(f"  [{c['date'][:10]}] {c['repo']}\n    {c['message']}")
    return '\n'.join(lines)


def format_prs_response(member_name, prs):
    if not prs:
        return _no_data(member_name, 'pull request')

    lines = [f"Open pull requests by {member_name}:\n"]
    for pr in prs:
        lines.append(
            f"  [{pr['repo']}] {pr['title']}\n"
            f"    Updated: {pr['updated'][:10]} | {pr['url']}"
        )
    return '\n'.join(lines)


def format_activity_response(member_name, jira_issues, commits, prs, repos=None):
    sections = []

    if jira_issues is not None:
        if jira_issues:
            lines = [f"JIRA ({len(jira_issues)} ticket{'s' if len(jira_issues) > 1 else ''}):"]
            for issue in jira_issues:
                est = _format_estimate(issue.get('estimate'))
                spent = _format_estimate(issue.get('timespent'))
                due = f" | Due: {issue['duedate']}" if issue.get('duedate') else ""
                est_str = f" | Est: {est}" if est else ""
                spent_str = f" | Spent: {spent}" if spent else ""
                lines.append(f"  {issue['key']} [{issue['status']}] [{issue['priority']}]{est_str}{spent_str}{due} {issue['summary']}")
            sections.append('\n'.join(lines))
        else:
            sections.append("JIRA: No recent activity.")

    if commits is not None:
        if commits:
            lines = [f"Commits ({len(commits)}):"]
            for c in commits:
                lines.append(f"  [{c['date'][:10]}] {c['repo']} — {c['message']}")
            sections.append('\n'.join(lines))
        else:
            sections.append("Commits: No recent activity.")

    if prs is not None:
        if prs:
            lines = [f"Pull Requests ({len(prs)} open):"]
            for pr in prs:
                lines.append(f"  [{pr['repo']}] {pr['title']}")
            sections.append('\n'.join(lines))
        else:
            sections.append("Pull Requests: None open.")

    if repos is not None:
        if repos:
            lines = [f"Repositories ({len(repos)} contributed to):"]
            for r in repos:
                lines.append(f"  {r['repo']}")
            sections.append('\n'.join(lines))
        else:
            sections.append("Repositories: No recent contributions.")

    header = f"Activity summary for {member_name} (last 7 days):\n"
    return header + '\n\n'.join(sections)
