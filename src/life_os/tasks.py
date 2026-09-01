from dataclasses import dataclass


@dataclass(frozen=True)
class Task:
    """A single actionable Life OS task."""

    title: str
    category: str


@dataclass(frozen=True)
class DailyPlan:
    """A structured set of tasks for one day."""

    revenue: list[Task]
    skill: list[Task]
    maintenance: list[Task]


def generate_tasks(goals: list[str]) -> DailyPlan:
    """Generate a structured daily task plan from active goals."""

    revenue_tasks = []
    skill_tasks = []
    maintenance_tasks = []

    for goal in goals:
        revenue_tasks.append(
            Task(
                title=f"Execute a direct revenue action for: {goal}",
                category="revenue",
            )
        )

        skill_tasks.append(
            Task(
                title=f"Improve a skill related to: {goal}",
                category="skill",
            )
        )

        maintenance_tasks.append(
            Task(
                title=f"Stabilize your environment for: {goal}",
                category="maintenance",
            )
        )

    return DailyPlan(
        revenue=revenue_tasks[:3],
        skill=skill_tasks[:3],
        maintenance=maintenance_tasks[:3],
    )