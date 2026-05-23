---
name: sonarqube-workflow
description: >-
  Fix SonarQube and SonarLint issues using the user-sonarqube MCP server together
  with IDE Problems/Linter diagnostics. Use when the user mentions SonarQube,
  SonarLint, quality gates, rule keys (e.g. S3776, S5852), code smells, cognitive
  complexity, security hotspots, or asks to clear Sonar errors in Problems.
---

# SonarQube workflow (MCP + IDE)

This repo uses SonarQube connected mode. **Project key** (do not guess):

```properties
# sonar-project.properties
sonar.projectKey=alias8818_enoch-agentic-research-system_6ab334f2-c45e-42db-87ce-a99310229989
```

Full workflow, MCP tool catalog, and fix loop: use the personal skill at `~/.cursor/skills/sonarqube-workflow/SKILL.md` (same content). Agents without that path should follow `.cursor/rules/sonarqube_mcp_instructions.mdc` plus the steps below.

## Quick loop

1. **`ReadLints`** on files you will edit (Problems panel = source of truth for what the user sees).
2. **`show_rule`** (`user-sonarqube` MCP) for the rule key (e.g. `python:S3776`, `typescript:S3776`).
3. **`search_sonar_issues_in_projects`** optional — open issues on same file/rule; not for instant post-fix verification.
4. Fix with minimal diff (extract helpers for S3776 / nested ternaries).
5. **`analyze_code_snippet`** with `projectKey` above, full `fileContent`, correct `language` + `scope` (`TEST` for `tests/**`, `*.test.ts`, `e2e/**`).
6. **`ReadLints`** again until ERRORs on touched lines are gone.
7. Run targeted tests; CI scan is authoritative on the server.

## MCP access

- Server: `user-sonarqube`
- Read schemas: `mcps/user-sonarqube/tools/*.json` (or Cursor MCP descriptors) before `CallMcpTool`.
- Supplementary rule file: `.cursor/rules/sonarqube_mcp_instructions.mdc`
