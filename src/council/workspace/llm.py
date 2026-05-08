"""
council/workspace/llm.py

Minimal LLM helper — invoke a single agent with a single task.
No loops, no phases, no orchestration. The caller controls everything.
"""

from __future__ import annotations

from crewai import Agent, Crew, Process, Task


def ask_agent(
    agent: Agent,
    description: str,
    expected_output: str = "",
    verbose: bool = False,
) -> str:
    """Run a single agent with a single task. Returns the raw output string."""
    task = Task(
        description=description,
        expected_output=expected_output or "Provide your response.",
        agent=agent,
    )

    crew = Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=verbose,
    )

    result = crew.kickoff()
    return result.raw if hasattr(result, "raw") else str(result)


def ask_agent_with_tools(
    agent: Agent,
    description: str,
    expected_output: str = "",
    context_tasks: list[Task] | None = None,
    verbose: bool = False,
) -> str:
    """Run an agent with optional context from previous tasks."""
    tasks = (context_tasks or []) + [
        Task(
            description=description,
            expected_output=expected_output or "Provide your response.",
            agent=agent,
        )
    ]

    crew = Crew(
        agents=[agent],
        tasks=tasks,
        process=Process.sequential,
        verbose=verbose,
    )

    result = crew.kickoff()
    return result.raw if hasattr(result, "raw") else str(result)
