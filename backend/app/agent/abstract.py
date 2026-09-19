from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, List, Optional

from app.core.exceptions import AppNotConnectedError
from app.tools.registry import ToolRegistry


class Agent(ABC):
    @abstractmethod
    async def run(self, task: str, context: dict[str, Any] = None, available_tools: list[str] = None, llm_provider: Any = None) -> dict[str, Any]:
        pass


class BaseAgent(Agent):
    def __init__(self, tool_registry: ToolRegistry, app_connections: dict[str, bool] = None):
        self._tool_registry = tool_registry
        self._app_connections = app_connections or {}

    def _is_app_connected(self, app_id: str) -> bool:
        return self._app_connections.get(app_id, False)

    def _select_tools_for_task(self, task: str, available_tools: List[str]) -> List[str]:
        task_lower = task.lower()

        # Intent-to-tool mapping for deterministic, intent-specific selection
        intent_tools: dict[str, List[str]] = {
            # GitHub intents
            "github_list_pull_requests": ["pull request", "pr ", "list pr", "open pr"],
            "github_create_pull_request": ["create pr", "create pull request", "make pr", "open a pr"],
            "github_list_repositories": ["repository", "repo", "list repos", "list repositories"],
            "github_get_issue": ["get issue", "show issue", "issue #", "issue number"],
            "github_list_issues": ["list issues", "show issues", "github issues"],
            # Slack intents
            "slack_send_message": ["send message", "post message", "send to slack", "slack message", "notify", "notification", "send a message"],
            "slack_list_channels": ["list channels", "show channels", "slack channels"],
            "slack_create_channel": ["create channel", "make channel", "new channel"],
            "slack_get_user_profile": ["user profile", "get user", "slack user"],
            # Grafana intents
            "grafana_query_logs": ["logs", "log entries", "error logs", "query logs"],
            "grafana_query_metrics": ["metrics", "metric", "query metrics"],
            "grafana_get_dashboard": ["dashboard", "get dashboard", "show dashboard"],
            "grafana_list_dashboards": ["list dashboards", "show dashboards", "grafana dashboards"],
            "grafana_get_alerts": ["alerts", "get alerts", "active alerts", "firing alerts"],
            "grafana_create_alert": ["create alert", "new alert", "make alert"],
            "grafana_get_annotations": ["annotations", "get annotations"],
            # Jira intents
            "jira_list_projects": ["jira projects", "list jira projects"],
            "jira_create_issue": ["create jira issue", "create issue", "new jira ticket"],
            "jira_get_issue": ["get jira issue", "jira issue", "show jira"],
            "jira_update_issue": ["update jira", "update issue", "transition issue"],
            # Linear intents
            "linear_list_projects": ["linear projects", "list linear projects"],
            "linear_create_issue": ["create linear issue", "linear issue", "new linear ticket"],
            "linear_get_issue": ["get linear issue", "linear issue"],
            "linear_list_issues": ["list linear issues", "linear issues"],
            # Notion intents
            "notion_list_pages": ["notion pages", "list notion pages"],
            "notion_create_page": ["create notion page", "new notion page"],
            "notion_get_page": ["get notion page", "notion page"],
            "notion_search_pages": ["search notion", "find notion"],
        }

        selected: List[str] = []
        for tool_name, keywords in intent_tools.items():
            for kw in keywords:
                if kw in task_lower:
                    if tool_name in available_tools and tool_name not in selected:
                        selected.append(tool_name)
                    break

        # If no specific intent matched, fall back to app-level keywords
        if not selected:
            app_keywords: dict[str, List[str]] = {
                "github": ["github", "code", "commit", "branch", "merge"],
                "slack": ["slack", "channel", "team", "chat"],
                "grafana": ["grafana", "monitor", "observability"],
                "jira": ["jira", "project", "ticket"],
                "linear": ["linear", "project", "issue", "ticket"],
                "notion": ["notion", "page", "doc", "document"],
            }
            matched_apps: List[str] = []
            for app_id, keywords in app_keywords.items():
                for kw in keywords:
                    if kw in task_lower:
                        if app_id not in matched_apps:
                            matched_apps.append(app_id)
                        break
            if matched_apps:
                selected = [t for t in available_tools if t.split("_")[0] in matched_apps]

        return selected

    def _summarize_tool_result(self, tool_name: str, data: dict[str, Any]) -> str:
        if tool_name == "github_list_pull_requests":
            prs = data.get("pull_requests", [])
            titles = [pr.get("title", "Untitled") for pr in prs]
            return f"Found {len(prs)} pull request(s): {'; '.join(titles)}."
        if tool_name == "github_list_repositories":
            repos = data.get("repositories", [])
            names = [r.get("name", "unknown") for r in repos]
            return f"Found {len(repos)} repository(ies): {'; '.join(names)}."
        if tool_name == "github_get_issue":
            issue = data.get("issue", {})
            return f"Issue #{issue.get('number', '?')}: {issue.get('title', 'Untitled')} ({issue.get('state', '?')})."
        if tool_name == "github_list_issues":
            issues = data.get("issues", [])
            return f"Found {len(issues)} issue(s): {'; '.join(i.get('title', 'Untitled') for i in issues)}."
        if tool_name == "github_create_pull_request":
            pr = data.get("pull_request", {})
            return f"Created PR #{pr.get('number', '?')}: {pr.get('title', 'Untitled')} -- {pr.get('status', '?')}."
        if tool_name == "slack_send_message":
            msg = data.get("message", {})
            return f"Message sent to {msg.get('channel', '?')}: \"{msg.get('text', '')[:50]}\"."
        if tool_name == "slack_list_channels":
            channels = data.get("channels", [])
            names = [c.get("name", "?") for c in channels]
            return f"Found {len(channels)} channel(s): {'; '.join(names)}."
        if tool_name == "slack_get_user_profile":
            user = data.get("user", {})
            return f"User: {user.get('name', '?')} ({user.get('email', '?')})."
        if tool_name == "grafana_get_dashboard":
            dash = data.get("dashboard", {})
            return f"Dashboard \"{dash.get('title', '?')}\" has {dash.get('panels', 0)} panel(s)."
        if tool_name == "grafana_list_dashboards":
            dashboards = data.get("dashboards", [])
            names = [d.get("title", "?") for d in dashboards]
            return f"Found {len(dashboards)} dashboard(s): {'; '.join(names)}."
        if tool_name == "grafana_query_logs":
            logs = data.get("logs", [])
            errors = [l for l in logs if l.get("level") == "error"]
            warns = [l for l in logs if l.get("level") == "warn"]
            parts = []
            if errors:
                parts.append(f"{len(errors)} error(s)")
            if warns:
                parts.append(f"{len(warns)} warning(s)")
            return f"Found {len(logs)} log entry(ies): {'; '.join(parts)}."
        if tool_name == "grafana_query_metrics":
            metrics = data.get("metrics", [])
            return f"Metric: {metrics[0].get('metric', '?')} = {metrics[0].get('value', '?')} {metrics[0].get('unit', '')}" if metrics else "No metrics found."
        if tool_name == "grafana_get_alerts":
            alerts = data.get("alerts", [])
            firing = [a for a in alerts if a.get("status") == "firing"]
            return f"Found {len(alerts)} alert(s), {len(firing)} firing."
        if tool_name == "grafana_get_annotations":
            annotations = data.get("annotations", [])
            return f"Found {len(annotations)} annotation(s)."
        if tool_name == "grafana_create_alert":
            alert = data.get("alert", {})
            return f"Created alert: {alert.get('name', '?')} -- {alert.get('status', '?')}."
        if tool_name == "jira_list_projects":
            projects = data.get("projects", [])
            return f"Found {len(projects)} project(s): {'; '.join(p.get('key', '?') for p in projects)}."
        if tool_name == "jira_create_issue":
            issue = data.get("issue", {})
            return f"Created issue {issue.get('key', '?')} -- {issue.get('status', '?')}."
        if tool_name == "jira_get_issue":
            issue = data.get("issue", {})
            return f"Issue {issue.get('key', '?')} is {issue.get('status', '?')}."
        if tool_name == "jira_update_issue":
            issue = data.get("issue", {})
            return f"Updated issue {issue.get('key', '?')} -- now {issue.get('status', '?')}."
        if tool_name == "linear_list_projects":
            projects = data.get("projects", [])
            return f"Found {len(projects)} project(s): {'; '.join(p.get('name', '?') for p in projects)}."
        if tool_name == "linear_create_issue":
            issue = data.get("issue", {})
            return f"Created issue {issue.get('id', '?')} -- {issue.get('status', '?')}."
        if tool_name == "linear_get_issue":
            issue = data.get("issue", {})
            return f"Issue {issue.get('id', '?')} is {issue.get('status', '?')}."
        if tool_name == "linear_list_issues":
            issues = data.get("issues", [])
            return f"Found {len(issues)} issue(s): {'; '.join(i.get('title', '?') for i in issues)}."
        if tool_name == "notion_list_pages":
            pages = data.get("pages", [])
            return f"Found {len(pages)} page(s): {'; '.join(p.get('title', '?') for p in pages)}."
        if tool_name == "notion_create_page":
            page = data.get("page", {})
            return f"Created page: {page.get('title', '?')}."
        if tool_name == "notion_get_page":
            page = data.get("page", {})
            return f"Page {page.get('id', '?')}: {page.get('content', '')[:60]}."
        if tool_name == "notion_search_pages":
            results = data.get("results", [])
            return f"Found {len(results)} result(s): {'; '.join(r.get('title', '?') for r in results)}."
        return data.get("summary", f"Executed {tool_name}")

    async def run(
        self,
        task: str,
        context: dict[str, Any] = None,
        available_tools: list[str] = None,
        llm_provider: Any = None,
    ) -> dict[str, Any]:
        ctx = context or {}
        events: list[dict[str, Any]] = []
        requested_tools = available_tools or self._tool_registry.list_tool_names()
        selected_tools = self._select_tools_for_task(task, requested_tools)

        if not selected_tools:
            events.append({
                "type": "intent_no_match",
                "task": task,
                "reason": "No matching tools found for this request",
            })
            llm_response = await self._generate_llm_response(task, llm_provider, "", events) if llm_provider else None
            response_msg = llm_response or f"Could not match '{task}' to any available tools."
            return {
                "status": "no_match",
                "events": events,
                "summary": f"Agent could not match task to available tools: {task}",
                "message": response_msg,
                "response": response_msg,
            }

        not_connected_apps: List[str] = []
        summaries: List[str] = []
        for tool_name in selected_tools:
            try:
                tool = self._tool_registry.get_tool(tool_name)
            except Exception:
                continue

            if not tool.enabled:
                continue

            if not self._is_app_connected(tool.app_id):
                if tool.app_id not in not_connected_apps:
                    not_connected_apps.append(tool.app_id)
                continue

            try:
                result = await self._tool_registry.execute_tool(tool_name, ctx.get("parameters", {}))
                events.append({
                    "type": "tool_executed",
                    "tool_name": tool_name,
                    "event": result["event"],
                    "data": result.get("data", {}),
                    "app_id": tool.app_id,
                })
                summaries.append(self._summarize_tool_result(tool_name, result.get("data", {})))
            except AppNotConnectedError:
                if tool.app_id not in not_connected_apps:
                    not_connected_apps.append(tool.app_id)
            except Exception:
                events.append({
                    "type": "tool_error",
                    "tool_name": tool_name,
                    "error": "Tool execution failed",
                })

        parts = []
        if summaries:
            parts.append(" ".join(summaries))
        for app_id in not_connected_apps:
            parts.append(f"{app_id.capitalize()} not connected to Nexus. Connect it to give me access.")
        if not parts:
            parts.append(f"Completed task: {task}.")

        raw_response = " ".join(parts)
        response_msg = await self._generate_llm_response(task, llm_provider, raw_response, events) if llm_provider else raw_response

        return {
            "status": "completed",
            "events": events,
            "summary": f"Agent completed task: {task}. {len([e for e in events if e['type'] == 'tool_executed'])} tool(s) executed.",
            "message": response_msg,
            "response": response_msg,
        }

    async def _generate_llm_response(
        self,
        task: str,
        llm_provider: Any,
        context_summary: str,
        events: list[dict[str, Any]],
    ) -> str:
        if not llm_provider:
            return context_summary
        try:
            system_msg = (
                f"You are Nexus, an AI assistant. "
                f"Context: {context_summary}\n"
                f"User task: {task}"
            )
            result = await llm_provider.chat(
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": task},
                ],
            )
            return result.get("content", context_summary)
        except Exception:
            return context_summary