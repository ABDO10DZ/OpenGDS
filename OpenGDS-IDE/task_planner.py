"""Validated, bounded task plans for the OpenGDS-IDE agent."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid


def build_task_plan(goal: str, steps: list[dict[str, Any]], available_tasks: list[dict[str, Any]]) -> dict[str, Any]:
    goal = str(goal or "").strip()
    if not goal or len(goal) > 2000:
        raise ValueError("Plan goal must contain 1–2000 characters.")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 8:
        raise ValueError("A task plan must contain between 1 and 8 steps.")
    known = {str(task.get("id")) for task in available_tasks}
    normalized = []
    for index, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            raise ValueError("Each plan step must be an object.")
        title = str(step.get("title", "")).strip()
        detail = str(step.get("description", "")).strip()
        task_id = str(step.get("task_id", "") or "").strip()
        if not title or len(title) > 160 or len(detail) > 1000:
            raise ValueError("Each step needs a title (max 160 chars); descriptions are limited to 1000 chars.")
        if task_id and task_id not in known:
            raise ValueError(f"Unknown project task id: {task_id}")
        normalized.append({
            "number": index,
            "title": title,
            "description": detail,
            "task_id": task_id or None,
            "status": "planned",
        })
    return {
        "id": uuid.uuid4().hex[:10],
        "goal": goal,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "awaiting_user_review",
        "steps": normalized,
        "execution_policy": "Each command requires separate explicit user approval. No automatic execution.",
    }
