#!/usr/bin/env python3
"""Mirror open SonarQube issues into Linear."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from typing import Any


SONAR_STATUSES = "OPEN,CONFIRMED"
LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"
SONAR_ENV = ("SONARQUBE_URL", "SONARQUBE_TOKEN", "SONARQUBE_PROJECT_KEY")
LINEAR_ENV = ("LINEAR_API_KEY", "LINEAR_TEAM_ID", "LINEAR_PROJECT_ID")


@dataclass(frozen=True)
class SonarIssue:
    key: str
    rule: str
    project: str
    component: str
    severity: str
    status: str
    message: str
    line: int | None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> SonarIssue:
        text_range = payload.get("textRange") or {}
        line = text_range.get("startLine")
        return cls(
            key=str(payload.get("key") or ""),
            rule=str(payload.get("rule") or ""),
            project=str(payload.get("project") or ""),
            component=str(payload.get("component") or ""),
            severity=str(payload.get("severity") or ""),
            status=str(payload.get("status") or ""),
            message=str(payload.get("message") or ""),
            line=int(line) if isinstance(line, int) else None,
        )

    @property
    def path(self) -> str:
        return self.component.split(":", 1)[-1]


@dataclass(frozen=True)
class SonarGroup:
    project: str
    component: str
    path: str
    line: int | None
    issues: tuple[SonarIssue, ...]

    @property
    def fingerprint(self) -> str:
        line = self.line if self.line is not None else "unknown"
        raw = f"{self.project}|{self.component}|{line}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    @property
    def marker(self) -> str:
        return f"<!-- sonar-linear-sync:{self.fingerprint} -->"

    @property
    def title(self) -> str:
        line = f":{self.line}" if self.line is not None else ""
        count = len(self.issues)
        suffix = "issue" if count == 1 else "issues"
        return f"SonarQube: {self.path}{line} ({count} {suffix})"


def group_issues(issues: list[SonarIssue]) -> list[SonarGroup]:
    grouped: dict[tuple[str, str, int | None], list[SonarIssue]] = defaultdict(list)
    for issue in issues:
        grouped[(issue.project, issue.component, issue.line)].append(issue)
    groups = [
        SonarGroup(
            project=project,
            component=component,
            path=items[0].path,
            line=line,
            issues=tuple(sorted(items, key=lambda item: (item.rule, item.key))),
        )
        for (project, component, line), items in grouped.items()
    ]
    return sorted(groups, key=lambda group: (group.path, group.line or 0))


def sonar_auth_header(token: str) -> str:
    encoded = base64.b64encode(f"{token}:".encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


def request_json(
    url: str,
    *,
    headers: dict[str, str],
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = None
    request_headers = dict(headers)
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{url} returned HTTP {exc.code}: {detail}") from exc


def fetch_sonar_issues(base_url: str, token: str, project_key: str) -> list[SonarIssue]:
    params = urllib.parse.urlencode(
        {
            "componentKeys": project_key,
            "statuses": SONAR_STATUSES,
            "ps": "500",
        }
    )
    url = f"{base_url.rstrip('/')}/api/issues/search?{params}"
    payload = request_json(url, headers={"Authorization": sonar_auth_header(token)})
    return [SonarIssue.from_api(issue) for issue in payload.get("issues", [])]


def sonar_issue_url(base_url: str, project_key: str, issue_key: str) -> str:
    params = urllib.parse.urlencode(
        {"id": project_key, "issues": issue_key, "open": issue_key}
    )
    return f"{base_url.rstrip('/')}/project/issues?{params}"


def linear_graphql(token: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    payload = request_json(
        LINEAR_GRAPHQL_URL,
        headers={"Authorization": token},
        data={"query": query, "variables": variables},
    )
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"], indent=2))
    return payload["data"]


def find_existing_issue(
    token: str, project_id: str, marker: str
) -> dict[str, Any] | None:
    query = """
query FindIssue($projectId: String!, $marker: String!) {
  issues(
    first: 1
    filter: {
      project: { id: { eq: $projectId } }
      description: { contains: $marker }
    }
  ) {
    nodes { id identifier title url }
  }
}
"""
    data = linear_graphql(token, query, {"projectId": project_id, "marker": marker})
    nodes = data["issues"]["nodes"]
    return nodes[0] if nodes else None


def build_description(group: SonarGroup, *, sonar_url: str, project_key: str) -> str:
    issue_lines = "\n".join(
        (
            f"- `{issue.key}` `{issue.rule}` `{issue.severity}` `{issue.status}`: "
            f"{issue.message} "
            f"({sonar_issue_url(sonar_url, project_key, issue.key)})"
        )
        for issue in group.issues
    )
    return f"""{group.marker}
## Source
- Tool/source: SonarQube
- Project: `{project_key}`
- Component: `{group.path}`
- Line: `{group.line if group.line is not None else "unknown"}`
- Open issue count: {len(group.issues)}

## Observed symptom or risk
SonarQube reports open issues for this file/line group. These create scanner debt that should be linked to a planned fix, mitigation, or accepted-risk decision instead of living only in SonarQube.

## Invariant
Every open SonarQube issue must have a Linear tracking record with the source issue key, planned fix or mitigation, and verification evidence.

## Root cause
Pending investigation. The SonarQube rule messages are:

{issue_lines}

## Planned fix or mitigation
- Inspect the affected file and rule messages.
- Patch the smallest root cause or record an accepted-risk rationale.
- Add or update deterministic tests when behavior can regress.
- Re-run SonarQube and update this issue with the result.

## Verification evidence
- Created or updated automatically by `scripts/sync_sonarqube_linear.py`.
- Closure requires a follow-up SonarQube search showing these keys fixed, accepted, or no longer open.

## Closure criteria
All SonarQube keys listed above are no longer open, or each has an explicit accepted-risk disposition with rationale.
"""


def create_or_update_linear_issue(
    group: SonarGroup,
    *,
    linear_token: str,
    team_id: str,
    project_id: str,
    parent_issue_id: str | None,
    label_ids: list[str],
    sonar_url: str,
    sonar_project_key: str,
) -> str:
    description = build_description(
        group, sonar_url=sonar_url, project_key=sonar_project_key
    )
    existing = find_existing_issue(linear_token, project_id, group.marker)
    if existing:
        mutation = """
mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) {
  issueUpdate(id: $id, input: $input) {
    success
    issue { identifier url }
  }
}
"""
        data = linear_graphql(
            linear_token,
            mutation,
            {
                "id": existing["id"],
                "input": {"title": group.title, "description": description},
            },
        )
        issue = data["issueUpdate"]["issue"]
        return f"updated {issue['identifier']} {issue['url']}"

    mutation = """
mutation CreateIssue($input: IssueCreateInput!) {
  issueCreate(input: $input) {
    success
    issue { identifier url }
  }
}
"""
    issue_input: dict[str, Any] = {
        "teamId": team_id,
        "projectId": project_id,
        "title": group.title,
        "description": description,
        "priority": 3,
    }
    if parent_issue_id:
        issue_input["parentId"] = parent_issue_id
    if label_ids:
        issue_input["labelIds"] = label_ids
    data = linear_graphql(linear_token, mutation, {"input": issue_input})
    issue = data["issueCreate"]["issue"]
    return f"created {issue['identifier']} {issue['url']}"


def env_required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def missing_env(names: tuple[str, ...]) -> list[str]:
    return [name for name in names if not os.environ.get(name, "").strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--skip-if-unconfigured",
        action="store_true",
        help="Exit successfully when required environment variables are missing.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    required_env = SONAR_ENV if args.dry_run else SONAR_ENV + LINEAR_ENV
    if args.skip_if_unconfigured:
        missing = missing_env(required_env)
        if missing:
            print(f"skip missing environment: {', '.join(missing)}")
            return
    sonar_url = env_required("SONARQUBE_URL")
    sonar_token = env_required("SONARQUBE_TOKEN")
    sonar_project_key = env_required("SONARQUBE_PROJECT_KEY")
    issues = fetch_sonar_issues(sonar_url, sonar_token, sonar_project_key)
    groups = group_issues(issues)
    if args.dry_run:
        print(f"sonar_groups={len(groups)} sonar_issues={len(issues)}")
        for group in groups:
            print(f"{group.fingerprint} {group.title}")
        return

    linear_token = env_required("LINEAR_API_KEY")
    linear_team_id = env_required("LINEAR_TEAM_ID")
    linear_project_id = env_required("LINEAR_PROJECT_ID")
    parent_issue_id = os.environ.get("LINEAR_PARENT_ISSUE_ID", "").strip() or None
    label_ids = [
        label.strip()
        for label in os.environ.get("LINEAR_LABEL_IDS", "").split(",")
        if label.strip()
    ]
    for group in groups:
        result = create_or_update_linear_issue(
            group,
            linear_token=linear_token,
            team_id=linear_team_id,
            project_id=linear_project_id,
            parent_issue_id=parent_issue_id,
            label_ids=label_ids,
            sonar_url=sonar_url,
            sonar_project_key=sonar_project_key,
        )
        print(result)
    print(
        f"ok synced {len(groups)} Linear issue groups from {len(issues)} SonarQube issues"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
