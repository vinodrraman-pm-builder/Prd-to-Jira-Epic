#!/usr/bin/env python3
"""
PRD to JIRA Epic Agent

Reads a Product Requirements Document and automatically creates a JIRA Epic
with all mandatory and key optional fields populated using Claude Opus 4.6.

Usage:
    python prd_to_jira_agent.py path/to/prd.md
    python prd_to_jira_agent.py path/to/prd.txt
    cat prd.md | python prd_to_jira_agent.py -

Required environment variables:
    ANTHROPIC_API_KEY   — Anthropic API key
    JIRA_URL            — JIRA instance URL  (e.g. https://company.atlassian.net)
    JIRA_EMAIL          — JIRA account email
    JIRA_API_TOKEN      — JIRA API token (generate at id.atlassian.com/manage-profile/security)
    JIRA_PROJECT_KEY    — Target project key  (e.g. PROD, ENG, PLATFORM)
"""

import json
import os
import sys
from typing import Any

import anthropic
import requests

# ── Configuration ──────────────────────────────────────────────────────────────

JIRA_URL = os.environ.get("JIRA_URL", "").rstrip("/")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN", "")
JIRA_PROJECT_KEY = os.environ.get("JIRA_PROJECT_KEY", "")

client = anthropic.Anthropic()

# ── JIRA helpers ───────────────────────────────────────────────────────────────

def _jira(method: str, path: str, **kwargs) -> requests.Response:
    """Make an authenticated JIRA REST API v3 request."""
    return requests.request(
        method,
        f"{JIRA_URL}/rest/api/3{path}",
        auth=(JIRA_EMAIL, JIRA_API_TOKEN),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        timeout=30,
        **kwargs,
    )


# ── Tool implementations ───────────────────────────────────────────────────────

def get_project_info(project_key: str) -> dict:
    """
    Return JIRA project metadata: available issue types, Epic-specific fields
    (with allowed values), components, and unreleased versions.
    """
    result: dict[str, Any] = {"project_key": project_key}

    # ── Issue types ──
    r = _jira("GET", f"/issue/createmeta/{project_key}/issuetypes")
    if r.status_code != 200:
        return {"error": f"Cannot fetch project metadata ({r.status_code}): {r.text}"}

    issue_types = r.json().get("issueTypes", [])
    result["issue_types"] = [{"id": it["id"], "name": it["name"]} for it in issue_types]

    # ── Epic fields ──
    for it in issue_types:
        if it["name"].lower() == "epic":
            fr = _jira("GET", f"/issue/createmeta/{project_key}/issuetypes/{it['id']}")
            if fr.status_code == 200:
                fields = fr.json().get("fields", {})
                result["epic_fields"] = {
                    k: {
                        "name": v.get("name"),
                        "required": v.get("required", False),
                        "type": v.get("schema", {}).get("type"),
                        "allowed_values": [
                            av.get("name", av.get("value", str(av)))
                            for av in v.get("allowedValues", [])[:20]
                        ] or None,
                    }
                    for k, v in fields.items()
                }
            break

    # ── Components ──
    cr = _jira("GET", f"/project/{project_key}/components")
    if cr.status_code == 200:
        result["components"] = [{"id": c["id"], "name": c["name"]} for c in cr.json()]

    # ── Unreleased versions ──
    vr = _jira("GET", f"/project/{project_key}/versions")
    if vr.status_code == 200:
        result["versions"] = [
            {"id": v["id"], "name": v["name"]}
            for v in vr.json()
            if not v.get("archived") and not v.get("released")
        ]

    return result


def search_jira_user(query: str) -> dict:
    """Search for a JIRA user by name or email; returns accountId list."""
    r = _jira("GET", "/user/search", params={"query": query, "maxResults": 5})
    if r.status_code == 200:
        return {
            "users": [
                {
                    "accountId": u["accountId"],
                    "displayName": u.get("displayName", ""),
                    "emailAddress": u.get("emailAddress", ""),
                }
                for u in r.json()
            ]
        }
    return {"error": f"User search failed ({r.status_code}): {r.text}", "users": []}


def _build_adf(sections: dict[str, str]) -> dict:
    """Convert description sections dict to Atlassian Document Format (ADF)."""
    section_titles = {
        "overview": "Overview",
        "problem_statement": "Problem Statement",
        "business_value": "Business Value",
        "scope_in": "In Scope",
        "scope_out": "Out of Scope",
        "requirements": "Key Requirements",
        "success_metrics": "Success Metrics & Acceptance Criteria",
        "dependencies": "Dependencies",
        "technical_notes": "Technical Considerations",
        "open_questions": "Open Questions",
    }

    content: list[dict] = []

    for key, title in section_titles.items():
        text = (sections.get(key) or "").strip()
        if not text:
            continue

        # Heading
        content.append({
            "type": "heading",
            "attrs": {"level": 2},
            "content": [{"type": "text", "text": title}],
        })

        # Split into lines; detect bullet lists
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        is_bullet = all(ln.startswith(("-", "•", "*")) for ln in lines)

        if is_bullet:
            content.append({
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [{
                            "type": "paragraph",
                            "content": [{"type": "text", "text": ln.lstrip("-•* ")}],
                        }],
                    }
                    for ln in lines
                ],
            })
        else:
            for ln in lines:
                content.append({
                    "type": "paragraph",
                    "content": [{"type": "text", "text": ln}],
                })

    return {"type": "doc", "version": 1, "content": content}


def create_jira_epic(
    summary: str,
    epic_name: str,
    description_sections: dict,
    priority: str,
    labels: list[str],
    components: list[str],
    story_points: int | None,
    due_date: str | None,
    assignee_account_id: str | None,
    fix_versions: list[str],
) -> dict:
    """
    Create a JIRA Epic.

    Args:
        summary              Epic title (max 255 chars).
        epic_name            Short name shown on sprint boards (max 60 chars).
        description_sections Keys: overview, problem_statement, business_value,
                             scope_in, scope_out, requirements, success_metrics,
                             dependencies, technical_notes, open_questions.
        priority             One of: Highest, High, Medium, Low, Lowest.
        labels               List of label strings (no spaces).
        components           List of component names that exist in the project.
        story_points         Fibonacci estimate: 1,2,3,5,8,13,21,40,100.
        due_date             ISO date string YYYY-MM-DD or null.
        assignee_account_id  JIRA accountId string or null.
        fix_versions         List of version names or empty list.
    """
    fields: dict[str, Any] = {
        "project": {"key": JIRA_PROJECT_KEY},
        "issuetype": {"name": "Epic"},
        "summary": summary[:255],
        "description": _build_adf(description_sections),
        "priority": {"name": priority},
        "labels": labels,
        # Epic Name — standard JIRA Software custom field
        "customfield_10011": epic_name[:60],
    }

    if components:
        fields["components"] = [{"name": c} for c in components]

    if story_points is not None:
        # customfield_10016 is the standard Story Points field in JIRA Software
        fields["customfield_10016"] = story_points
        fields["story_points"] = story_points  # fallback alias

    if due_date:
        fields["duedate"] = due_date

    if assignee_account_id:
        fields["assignee"] = {"accountId": assignee_account_id}

    if fix_versions:
        fields["fixVersions"] = [{"name": v} for v in fix_versions]

    r = _jira("POST", "/issue", json={"fields": fields})

    if r.status_code == 201:
        key = r.json()["key"]
        return {
            "success": True,
            "issue_key": key,
            "issue_url": f"{JIRA_URL}/browse/{key}",
            "message": f"✅ Epic {key} created successfully!",
        }

    # Surface useful error details
    try:
        err = r.json()
    except Exception:
        err = {"raw": r.text}
    return {
        "success": False,
        "status_code": r.status_code,
        "error": r.text[:500],
        "jira_errors": err,
    }


# ── Tool registry ──────────────────────────────────────────────────────────────

TOOLS: list[dict] = [
    {
        "name": "get_project_info",
        "description": (
            "Fetch JIRA project metadata: available issue types, Epic-specific fields "
            "(with allowed values and whether they are required), components, and "
            "unreleased fix versions. Call this first to understand what values are "
            "valid before creating the epic."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_key": {
                    "type": "string",
                    "description": "JIRA project key, e.g. PROD or ENG.",
                }
            },
            "required": ["project_key"],
        },
    },
    {
        "name": "search_jira_user",
        "description": (
            "Search for a JIRA user by display name or email address. "
            "Use this when the PRD mentions a specific owner/assignee. "
            "Returns a list of matching users with their accountId."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Name or email to search for.",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "create_jira_epic",
        "description": (
            "Create a JIRA Epic with all mandatory and optional fields populated. "
            "Call this only after you have fetched project metadata and resolved "
            "any assignee. This is the final step."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Epic title, max 255 characters.",
                },
                "epic_name": {
                    "type": "string",
                    "description": "Short epic label shown on sprint boards, max 60 chars.",
                },
                "description_sections": {
                    "type": "object",
                    "description": (
                        "Structured description. All values are strings. "
                        "Use markdown-style bullet lines (starting with '- ') for lists."
                    ),
                    "properties": {
                        "overview": {"type": "string"},
                        "problem_statement": {"type": "string"},
                        "business_value": {"type": "string"},
                        "scope_in": {"type": "string"},
                        "scope_out": {"type": "string"},
                        "requirements": {"type": "string"},
                        "success_metrics": {"type": "string"},
                        "dependencies": {"type": "string"},
                        "technical_notes": {"type": "string"},
                        "open_questions": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "priority": {
                    "type": "string",
                    "enum": ["Highest", "High", "Medium", "Low", "Lowest"],
                    "description": "Epic priority. Infer from urgency language in the PRD.",
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Labels (no spaces). Derive from product area, team, or type.",
                },
                "components": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Component names that exist in the project. Use exact names from get_project_info.",
                },
                "story_points": {
                    "type": "integer",
                    "description": "High-level effort estimate (Fibonacci: 1,2,3,5,8,13,21,40,100). Null if unknown.",
                },
                "due_date": {
                    "type": "string",
                    "description": "Target date in YYYY-MM-DD format. Null if not specified.",
                },
                "assignee_account_id": {
                    "type": "string",
                    "description": "JIRA accountId from search_jira_user. Null if not specified.",
                },
                "fix_versions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Target release version names. Use exact names from get_project_info.",
                },
            },
            "required": [
                "summary",
                "epic_name",
                "description_sections",
                "priority",
                "labels",
                "components",
                "story_points",
                "due_date",
                "assignee_account_id",
                "fix_versions",
            ],
        },
    },
]

# ── Tool dispatch ──────────────────────────────────────────────────────────────

def dispatch(name: str, inputs: dict) -> str:
    if name == "get_project_info":
        result = get_project_info(**inputs)
    elif name == "search_jira_user":
        result = search_jira_user(**inputs)
    elif name == "create_jira_epic":
        result = create_jira_epic(**inputs)
    else:
        result = {"error": f"Unknown tool: {name}"}
    return json.dumps(result, indent=2)


# ── System prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = f"""You are an expert Product Manager assistant that converts Product Requirements \
Documents (PRDs) into well-structured JIRA Epics.

JIRA project: {JIRA_PROJECT_KEY}
JIRA instance: {JIRA_URL}

Your workflow:
1. Read and deeply understand the PRD.
2. Call get_project_info("{JIRA_PROJECT_KEY}") to discover available components, \
versions, and which Epic fields are required.
3. If the PRD names a specific owner or assignee, call search_jira_user to resolve \
their JIRA accountId.
4. Call create_jira_epic with every field populated.

Field guidelines:
• summary        — Clear, action-oriented title. Start with a verb or noun phrase.
• epic_name      — Ultra-short label (≤60 chars) for sprint boards.
• description_sections — Fill as many sections as the PRD supports. Use bullet lines \
("- item") for lists. Be thorough: PMs should be able to hand this to an engineer cold.
• priority       — Map urgency: "must ship next sprint" → High/Highest; \
"nice to have" → Low; default → Medium.
• labels         — 3–6 labels. Include product area, feature type, and team if inferrable.
• story_points   — Estimate relative complexity: small feature ≈ 5–8, \
medium ≈ 13–21, large ≈ 40+. Use null only if truly impossible to estimate.
• components     — Only use names returned by get_project_info; skip if none match.
• fix_versions   — Only use names returned by get_project_info; skip if none match.
• due_date       — Extract explicit deadlines or milestones from the PRD; null otherwise.

After create_jira_epic succeeds, print a concise summary of what was filed, \
including the issue key and URL."""


# ── Agent loop ─────────────────────────────────────────────────────────────────

def run_agent(prd_text: str) -> None:
    """Run the agentic loop: stream Claude's output and execute tool calls."""

    print("\n" + "═" * 60)
    print("  PRD → JIRA Epic Agent")
    print("═" * 60)
    print(f"  Project : {JIRA_PROJECT_KEY}")
    print(f"  JIRA    : {JIRA_URL}")
    print(f"  PRD     : {len(prd_text):,} characters")
    print("═" * 60 + "\n")

    messages: list[dict] = [
        {
            "role": "user",
            "content": (
                f"Please analyze the following PRD and create a JIRA Epic for it.\n\n"
                f"<prd>\n{prd_text}\n</prd>"
            ),
        }
    ]

    while True:
        tool_use_blocks: list[dict] = []
        current_text = ""

        # Stream the response
        with client.messages.stream(
            model="claude-opus-4-6",
            max_tokens=8192,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        ) as stream:
            for event in stream:
                if event.type == "content_block_start":
                    if event.content_block.type == "thinking":
                        print("\n[Thinking...]\n", flush=True)
                    elif event.content_block.type == "text":
                        if current_text:
                            print()  # newline between text blocks
                elif event.type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "thinking_delta":
                        print(delta.thinking, end="", flush=True)
                    elif delta.type == "text_delta":
                        print(delta.text, end="", flush=True)
                        current_text += delta.text

            final = stream.get_final_message()

        print(flush=True)

        # Collect tool-use blocks
        for block in final.content:
            if block.type == "tool_use":
                tool_use_blocks.append(block)

        # Append assistant turn
        messages.append({"role": "assistant", "content": final.content})

        if final.stop_reason == "end_turn" or not tool_use_blocks:
            break

        # Execute each tool and collect results
        tool_results = []
        for block in tool_use_blocks:
            print(f"\n⚙  Calling tool: {block.name}", flush=True)
            if block.input:
                # Show key inputs without flooding the terminal
                for k, v in list(block.input.items())[:3]:
                    preview = str(v)[:80] + ("…" if len(str(v)) > 80 else "")
                    print(f"   {k}: {preview}", flush=True)

            result_str = dispatch(block.name, block.input)

            # Peek at success/error for the user
            try:
                result_obj = json.loads(result_str)
                if "message" in result_obj:
                    print(f"   → {result_obj['message']}", flush=True)
                elif "error" in result_obj:
                    print(f"   ✗ Error: {result_obj['error'][:120]}", flush=True)
                elif isinstance(result_obj, dict):
                    keys = list(result_obj.keys())[:4]
                    print(f"   → OK ({', '.join(keys)})", flush=True)
            except Exception:
                pass

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_str,
            })

        messages.append({"role": "user", "content": tool_results})

    print("\n" + "═" * 60)
    print("  Done.")
    print("═" * 60 + "\n")


# ── Entry point ────────────────────────────────────────────────────────────────

def _validate_env() -> list[str]:
    missing = []
    for var in ("ANTHROPIC_API_KEY", "JIRA_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_PROJECT_KEY"):
        if not os.environ.get(var):
            missing.append(var)
    return missing


def main() -> None:
    missing = _validate_env()
    if missing:
        print("❌  Missing required environment variables:", file=sys.stderr)
        for var in missing:
            print(f"    {var}", file=sys.stderr)
        print(
            "\nSet them and retry. See the module docstring for details.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Read PRD from file argument or stdin
    if len(sys.argv) == 2 and sys.argv[1] != "-":
        path = sys.argv[1]
        try:
            with open(path, "r", encoding="utf-8") as f:
                prd_text = f.read()
        except FileNotFoundError:
            print(f"❌  File not found: {path}", file=sys.stderr)
            sys.exit(1)
    else:
        if sys.stdin.isatty():
            print("Paste your PRD below, then press Ctrl+D (Unix) or Ctrl+Z (Windows):")
        prd_text = sys.stdin.read()

    prd_text = prd_text.strip()
    if not prd_text:
        print("❌  No PRD content provided.", file=sys.stderr)
        sys.exit(1)

    run_agent(prd_text)


if __name__ == "__main__":
    main()
