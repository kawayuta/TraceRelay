from __future__ import annotations

from .models import TaskRun, TaskSpec
from .task_runtime import TaskRuntime


def run_prompt(prompt: str, runtime: TaskRuntime | None = None) -> TaskRun:
    active_runtime = runtime or TaskRuntime()
    return active_runtime.run_task(TaskSpec(prompt=prompt))
