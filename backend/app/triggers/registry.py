from __future__ import annotations

from typing import Any, Optional


TRIGGER_TYPES: dict[str, dict[str, Any]] = {
    "manual": {
        "id": "manual",
        "label": "Manual",
        "app_id": None,
        "events": ["manual"],
        "description": "Run the workflow on demand via API or UI",
    },
    "schedule": {
        "id": "schedule",
        "label": "Schedule",
        "app_id": None,
        "events": ["schedule.tick"],
        "description": "Run the workflow on a cron schedule",
    },
    "webhook": {
        "id": "webhook",
        "label": "Webhook",
        "app_id": None,
        "events": ["webhook.received"],
        "description": "Run the workflow when an HTTP webhook is received",
    },
    "github": {
        "id": "github",
        "label": "GitHub",
        "app_id": "github",
        "events": [
            "github.repo.created",
            "github.repo.updated",
            "github.repo.deleted",
            "github.repo.archived",
            "github.pull_request.opened",
            "github.pull_request.closed",
            "github.pull_request.reopened",
            "github.pull_request.merged",
            "github.pull_request.updated",
            "github.pull_request.review_requested",
            "github.pull_request.review_submitted",
            "github.issue.opened",
            "github.issue.closed",
            "github.issue.reopened",
            "github.issue.updated",
            "github.issue.labeled",
            "github.issue.assigned",
            "github.push",
            "github.branch.created",
            "github.release.published",
            "github.release.created",
            "github.release.updated",
            "github.workflow_run.completed",
            "github.workflow_run.requested",
            "github.member.added",
            "github.member.removed",
        ],
        "description": "Trigger workflows on GitHub repository, PR, issue, and push events",
    },
    "slack": {
        "id": "slack",
        "label": "Slack",
        "app_id": "slack",
        "events": [
            "slack.message.received",
            "slack.channel.created",
            "slack.member.joined",
            "slack.app_mention",
            "slack.reaction.added",
            "slack.reaction.removed",
            "slack.member.left",
        ],
        "description": "Trigger workflows on Slack messages, channel, and member events",
    },
    "jira": {
        "id": "jira",
        "label": "Jira",
        "app_id": "jira",
        "events": [
            "jira.issue.created",
            "jira.issue.updated",
            "jira.issue.closed",
            "jira.issue.reopened",
            "jira.issue.assigned",
            "jira.issue.labeled",
            "jira.issue.commented",
            "jira.project.created",
            "jira.sprint.created",
            "jira.sprint.started",
            "jira.sprint.completed",
        ],
        "description": "Trigger workflows on Jira issue, project, and sprint events",
    },
    "linear": {
        "id": "linear",
        "label": "Linear",
        "app_id": "linear",
        "events": [
            "linear.issue.created",
            "linear.issue.updated",
            "linear.issue.closed",
            "linear.issue.reopened",
            "linear.issue.assigned",
            "linear.issue.moved",
            "linear.project.created",
            "linear.project.updated",
            "linear.cycle.created",
            "linear.cycle.updated",
        ],
        "description": "Trigger workflows on Linear issue, project, and cycle events",
    },
    "notion": {
        "id": "notion",
        "label": "Notion",
        "app_id": "notion",
        "events": [
            "notion.page.created",
            "notion.page.updated",
            "notion.page.published",
            "notion.page.archived",
            "notion.database.created",
            "notion.database.updated",
            "notion.comment.created",
        ],
        "description": "Trigger workflows on Notion page, database, and comment events",
    },
    "grafana": {
        "id": "grafana",
        "label": "Grafana",
        "app_id": "grafana",
        "events": [
            "grafana.alert.firing",
            "grafana.alert.resolved",
            "grafana.alert.created",
            "grafana.dashboard.created",
            "grafana.dashboard.updated",
            "grafana.annotation.created",
        ],
        "description": "Trigger workflows on Grafana alert, dashboard, and annotation events",
    },
}


def list_trigger_types() -> list[dict[str, Any]]:
    return [dict(v) for v in TRIGGER_TYPES.values()]


def list_trigger_events(app_id: Optional[str] = None) -> list[str]:
    events: list[str] = []
    for trigger in TRIGGER_TYPES.values():
        if app_id and trigger.get("app_id") != app_id:
            continue
        events.extend(trigger["events"])
    return sorted(set(events))


def get_trigger_handler(trigger_id: str) -> Optional[dict[str, Any]]:
    return TRIGGER_TYPES.get(trigger_id)


def is_valid_event(event_name: str) -> bool:
    for trigger in TRIGGER_TYPES.values():
        if event_name in trigger["events"]:
            return True
    return False


def get_app_for_event(event_name: str) -> Optional[str]:
    for trigger in TRIGGER_TYPES.values():
        if event_name in trigger["events"]:
            return trigger.get("app_id")
    return None