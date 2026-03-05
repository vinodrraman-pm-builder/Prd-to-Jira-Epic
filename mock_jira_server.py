#!/usr/bin/env python3
"""
Dummy Jira REST API Server

Mimics the Jira REST API v3 endpoints used by prd_to_jira_agent.py so you can
test the agent locally without a real Jira instance.

Run:
    python mock_jira_server.py

Then in a second terminal set your env vars and run the agent:
    bash run_test.sh
"""

import json
import uuid
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

# ── In-memory store ────────────────────────────────────────────────────────────

ISSUES: dict[str, dict] = {}   # key → issue dict
issue_counter = [1]            # mutable counter

PROJECT_KEY = "DEMO"

ISSUE_TYPES = [
    {"id": "10000", "name": "Epic",    "description": "A big chunk of work."},
    {"id": "10001", "name": "Story",   "description": "A user story."},
    {"id": "10002", "name": "Task",    "description": "A generic task."},
    {"id": "10003", "name": "Bug",     "description": "A bug report."},
    {"id": "10004", "name": "Subtask", "description": "A subtask."},
]

EPIC_FIELDS = {
    "summary": {
        "name": "Summary",
        "required": True,
        "schema": {"type": "string"},
        "allowedValues": [],
    },
    "description": {
        "name": "Description",
        "required": False,
        "schema": {"type": "doc"},
        "allowedValues": [],
    },
    "priority": {
        "name": "Priority",
        "required": False,
        "schema": {"type": "priority"},
        "allowedValues": [
            {"name": "Highest"}, {"name": "High"}, {"name": "Medium"},
            {"name": "Low"}, {"name": "Lowest"},
        ],
    },
    "labels": {
        "name": "Labels",
        "required": False,
        "schema": {"type": "array", "items": "string"},
        "allowedValues": [],
    },
    "components": {
        "name": "Component/s",
        "required": False,
        "schema": {"type": "array", "items": "component"},
        "allowedValues": [
            {"id": "10100", "name": "Frontend"},
            {"id": "10101", "name": "Backend"},
            {"id": "10102", "name": "Data Platform"},
            {"id": "10103", "name": "Search"},
            {"id": "10104", "name": "Infrastructure"},
        ],
    },
    "duedate": {
        "name": "Due date",
        "required": False,
        "schema": {"type": "date"},
        "allowedValues": [],
    },
    "assignee": {
        "name": "Assignee",
        "required": False,
        "schema": {"type": "user"},
        "allowedValues": [],
    },
    "fixVersions": {
        "name": "Fix Version/s",
        "required": False,
        "schema": {"type": "array", "items": "version"},
        "allowedValues": [
            {"id": "20001", "name": "v4.1"},
            {"id": "20002", "name": "v4.2"},
            {"id": "20003", "name": "v4.3"},
        ],
    },
    "customfield_10011": {
        "name": "Epic Name",
        "required": True,
        "schema": {"type": "string", "custom": "epic-name"},
        "allowedValues": [],
    },
    "customfield_10016": {
        "name": "Story Points",
        "required": False,
        "schema": {"type": "number", "custom": "story-points"},
        "allowedValues": [],
    },
}

USERS = [
    {
        "accountId": "uid-sarah-chen-001",
        "displayName": "Sarah Chen",
        "emailAddress": "sarah.chen@example.com",
        "active": True,
    },
    {
        "accountId": "uid-james-patel-002",
        "displayName": "James Patel",
        "emailAddress": "james.patel@example.com",
        "active": True,
    },
    {
        "accountId": "uid-alex-kim-003",
        "displayName": "Alex Kim",
        "emailAddress": "alex.kim@example.com",
        "active": True,
    },
]

# ── Auth middleware (permissive — any non-empty token accepted) ─────────────────

def _check_auth():
    auth = request.authorization
    if not auth:
        return jsonify({"errorMessages": ["Unauthorized"]}), 401
    return None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/rest/api/3/issue/createmeta/<project_key>/issuetypes")
def get_issuetypes(project_key):
    err = _check_auth()
    if err:
        return err
    return jsonify({"issueTypes": ISSUE_TYPES})


@app.get("/rest/api/3/issue/createmeta/<project_key>/issuetypes/<issuetype_id>")
def get_issuetype_fields(project_key, issuetype_id):
    err = _check_auth()
    if err:
        return err
    return jsonify({"fields": EPIC_FIELDS})


@app.get("/rest/api/3/project/<project_key>/components")
def get_components(project_key):
    err = _check_auth()
    if err:
        return err
    components = [
        {"id": "10100", "name": "Frontend"},
        {"id": "10101", "name": "Backend"},
        {"id": "10102", "name": "Data Platform"},
        {"id": "10103", "name": "Search"},
        {"id": "10104", "name": "Infrastructure"},
    ]
    return jsonify(components)


@app.get("/rest/api/3/project/<project_key>/versions")
def get_versions(project_key):
    err = _check_auth()
    if err:
        return err
    versions = [
        {"id": "20001", "name": "v4.1", "released": True,  "archived": False},
        {"id": "20002", "name": "v4.2", "released": False, "archived": False},
        {"id": "20003", "name": "v4.3", "released": False, "archived": False},
    ]
    return jsonify(versions)


@app.get("/rest/api/3/user/search")
def user_search():
    err = _check_auth()
    if err:
        return err
    query = (request.args.get("query") or "").lower()
    results = [
        u for u in USERS
        if query in u["displayName"].lower() or query in u["emailAddress"].lower()
    ]
    if not results:
        results = USERS  # return all if no match (permissive for testing)
    return jsonify(results[: int(request.args.get("maxResults", 5))])


@app.post("/rest/api/3/issue")
def create_issue():
    err = _check_auth()
    if err:
        return err

    body = request.get_json(force=True) or {}
    fields = body.get("fields", {})

    # Validate required fields
    errors = {}
    if not fields.get("summary"):
        errors["summary"] = ["Field required"]
    if not fields.get("issuetype"):
        errors["issuetype"] = ["Field required"]

    if errors:
        return jsonify({"errorMessages": [], "errors": errors}), 400

    # Generate a key
    n = issue_counter[0]
    issue_counter[0] += 1
    key = f"{PROJECT_KEY}-{n}"

    issue = {
        "id": str(uuid.uuid4()),
        "key": key,
        "fields": fields,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    ISSUES[key] = issue

    print(f"\n{'='*60}")
    print(f"  NEW ISSUE CREATED: {key}")
    print(f"{'='*60}")
    print(f"  Summary  : {fields.get('summary', '')}")
    epic_name = fields.get("customfield_10011", "")
    if epic_name:
        print(f"  Epic Name: {epic_name}")
    priority = (fields.get("priority") or {}).get("name", "")
    if priority:
        print(f"  Priority : {priority}")
    labels = fields.get("labels", [])
    if labels:
        print(f"  Labels   : {', '.join(labels)}")
    comps = [c.get("name", "") for c in fields.get("components", [])]
    if comps:
        print(f"  Components: {', '.join(comps)}")
    sp = fields.get("customfield_10016") or fields.get("story_points")
    if sp:
        print(f"  Story Pts: {sp}")
    due = fields.get("duedate", "")
    if due:
        print(f"  Due Date : {due}")
    vers = [v.get("name", "") for v in fields.get("fixVersions", [])]
    if vers:
        print(f"  Versions : {', '.join(vers)}")
    assignee = (fields.get("assignee") or {}).get("accountId", "")
    if assignee:
        print(f"  Assignee : {assignee}")
    print(f"{'='*60}\n")

    return jsonify({"id": issue["id"], "key": key, "self": f"http://localhost:8080/browse/{key}"}), 201


@app.get("/browse/<issue_key>")
def browse_issue(issue_key):
    issue = ISSUES.get(issue_key)
    if not issue:
        return f"Issue {issue_key} not found", 404

    fields = issue["fields"]
    desc_sections = ""
    desc = fields.get("description") or {}
    if desc.get("content"):
        for node in desc["content"]:
            if node.get("type") == "heading":
                text = "".join(t.get("text", "") for t in node.get("content", []))
                desc_sections += f"<h3>{text}</h3>"
            elif node.get("type") == "paragraph":
                text = "".join(t.get("text", "") for t in node.get("content", []))
                desc_sections += f"<p>{text}</p>"
            elif node.get("type") == "bulletList":
                desc_sections += "<ul>"
                for item in node.get("content", []):
                    for para in item.get("content", []):
                        text = "".join(t.get("text", "") for t in para.get("content", []))
                        desc_sections += f"<li>{text}</li>"
                desc_sections += "</ul>"

    html = f"""<!DOCTYPE html>
<html>
<head>
  <title>{issue_key}</title>
  <style>
    body {{ font-family: -apple-system, sans-serif; margin: 0; background: #f4f5f7; }}
    .header {{ background: #0052cc; color: white; padding: 12px 24px; font-size: 18px; }}
    .container {{ max-width: 900px; margin: 24px auto; background: white;
                  border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,.15); padding: 24px; }}
    .badge {{ display:inline-block; background:#e3fcef; color:#006644;
              border-radius:4px; padding:2px 8px; font-size:12px; font-weight:600; }}
    .label {{ display:inline-block; background:#dfe1e6; border-radius:2px;
              padding:2px 6px; font-size:11px; margin:2px; }}
    h1 {{ color:#172b4d; font-size:22px; margin-top:0; }}
    h2 {{ color:#344563; font-size:15px; border-bottom:1px solid #dfe1e6; padding-bottom:6px; }}
    table {{ border-collapse:collapse; width:100%; }}
    td {{ padding:6px 12px; border-bottom:1px solid #f0f0f0; vertical-align:top; }}
    td:first-child {{ width:140px; color:#6b778c; font-size:13px; }}
  </style>
</head>
<body>
  <div class="header">🎯 Dummy Jira &nbsp;›&nbsp; {issue_key}</div>
  <div class="container">
    <span class="badge">EPIC</span>
    <h1>{fields.get('summary', '')}</h1>
    <table>
      <tr><td>Epic Name</td><td>{fields.get('customfield_10011', '')}</td></tr>
      <tr><td>Priority</td><td>{(fields.get('priority') or {{}}).get('name', '-')}</td></tr>
      <tr><td>Story Points</td><td>{fields.get('customfield_10016') or fields.get('story_points') or '-'}</td></tr>
      <tr><td>Due Date</td><td>{fields.get('duedate') or '-'}</td></tr>
      <tr><td>Components</td><td>{', '.join(c.get('name','') for c in fields.get('components',[]))  or '-'}</td></tr>
      <tr><td>Fix Versions</td><td>{', '.join(v.get('name','') for v in fields.get('fixVersions',[]))  or '-'}</td></tr>
      <tr><td>Assignee</td><td>{(fields.get('assignee') or {{}}).get('accountId', '-')}</td></tr>
      <tr><td>Labels</td>
          <td>{''.join(f'<span class="label">{l}</span>' for l in fields.get('labels',[]))  or '-'}</td></tr>
      <tr><td>Created</td><td>{issue['created_at']}</td></tr>
    </table>
    <h2 style="margin-top:24px;">Description</h2>
    {desc_sections or '<p style="color:#6b778c">No description.</p>'}
  </div>
</body>
</html>"""
    return html, 200, {"Content-Type": "text/html"}


@app.get("/")
def index():
    rows = ""
    for key, issue in ISSUES.items():
        fields = issue["fields"]
        rows += (
            f"<tr>"
            f"<td><a href='/browse/{key}'>{key}</a></td>"
            f"<td>{fields.get('summary','')[:80]}</td>"
            f"<td>{(fields.get('priority') or {{}}).get('name','-')}</td>"
            f"<td>{fields.get('duedate') or '-'}</td>"
            f"</tr>"
        )
    if not rows:
        rows = "<tr><td colspan='4' style='color:#999;text-align:center'>No issues yet — run the agent!</td></tr>"

    html = f"""<!DOCTYPE html>
<html>
<head>
  <title>Dummy Jira</title>
  <style>
    body {{ font-family:-apple-system,sans-serif; margin:0; background:#f4f5f7; }}
    .header {{ background:#0052cc; color:white; padding:14px 24px; font-size:20px; }}
    .container {{ max-width:900px; margin:24px auto; background:white;
                  border-radius:4px; box-shadow:0 1px 3px rgba(0,0,0,.15); padding:24px; }}
    table {{ border-collapse:collapse; width:100%; }}
    th {{ text-align:left; padding:8px 12px; background:#f4f5f7; color:#6b778c; font-size:12px; }}
    td {{ padding:8px 12px; border-bottom:1px solid #f0f0f0; font-size:14px; }}
    a {{ color:#0052cc; text-decoration:none; font-weight:600; }}
  </style>
</head>
<body>
  <div class="header">🎯 Dummy Jira &nbsp;—&nbsp; Project: DEMO</div>
  <div class="container">
    <h2 style="color:#344563;margin-top:0">Epics ({len(ISSUES)})</h2>
    <table>
      <thead><tr><th>Key</th><th>Summary</th><th>Priority</th><th>Due Date</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</body>
</html>"""
    return html, 200, {"Content-Type": "text/html"}


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  Dummy Jira Server")
    print("=" * 60)
    print("  URL       : http://localhost:8080")
    print("  Dashboard : http://localhost:8080/")
    print("  Project   : DEMO")
    print()
    print("  Ready. Run the agent with:  bash run_test.sh")
    print("=" * 60)
    app.run(host="0.0.0.0", port=8080, debug=False)
