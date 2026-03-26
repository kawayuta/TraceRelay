from __future__ import annotations

from mcp.server.fastmcp import FastMCP


PROMPTS = {
    "investigate_subject": {
        "name": "investigate_subject",
        "description": "Investigate a subject with task-first runtime semantics.",
        "arguments": ["subject"],
    },
    "compare_subjects": {
        "name": "compare_subjects",
        "description": "Compare two subjects.",
        "arguments": ["left", "right"],
    },
    "analyze_policy": {
        "name": "analyze_policy",
        "description": "Analyze a policy package in structured form.",
        "arguments": ["subject"],
    },
    "analyze_incident": {
        "name": "analyze_incident",
        "description": "Analyze a system incident in structured form.",
        "arguments": ["subject"],
    },
}


def list_prompts() -> list[dict[str, object]]:
    return [dict(value) for value in PROMPTS.values()]


def render_prompt(name: str, arguments: dict[str, str]) -> str:
    if name == "investigate_subject":
        return f"{arguments['subject']}について構造化して調査して"
    if name == "compare_subjects":
        return f"{arguments['left']}と{arguments['right']}を比較して構造化して"
    if name == "analyze_policy":
        return f"{arguments['subject']}の政策パッケージを構造化して"
    if name == "analyze_incident":
        return f"{arguments['subject']}障害を構造化して"
    raise KeyError(name)


def register_prompts(mcp: FastMCP) -> None:
    @mcp.prompt(
        name="investigate_subject",
        description="Investigate a subject with task-first runtime semantics.",
    )
    def investigate_subject(subject: str) -> str:
        return render_prompt("investigate_subject", {"subject": subject})

    @mcp.prompt(
        name="compare_subjects",
        description="Compare two subjects.",
    )
    def compare_subjects(left: str, right: str) -> str:
        return render_prompt("compare_subjects", {"left": left, "right": right})

    @mcp.prompt(
        name="analyze_policy",
        description="Analyze a policy package in structured form.",
    )
    def analyze_policy(subject: str) -> str:
        return render_prompt("analyze_policy", {"subject": subject})

    @mcp.prompt(
        name="analyze_incident",
        description="Analyze a system incident in structured form.",
    )
    def analyze_incident(subject: str) -> str:
        return render_prompt("analyze_incident", {"subject": subject})
