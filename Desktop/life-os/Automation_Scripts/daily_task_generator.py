"""
Life OS — Daily Task Generator
================================
Automatically generates a 9-task daily plan across 3 categories
based on the user's active goals.

Usage:
    python daily_task_generator.py

Customize the `goals` list at the bottom to match your current focus areas.
"""


def generate_tasks(goals: list[str]) -> dict[str, list[str]]:
    """
    Generate a structured 9-task daily plan from a list of goals.

    Args:
        goals: List of goal areas (e.g., ["business", "fitness", "learning"])

    Returns:
        Dictionary with revenue, skill, and maintenance task lists.
    """
    revenue_tasks = []
    skill_tasks = []
    maintenance_tasks = []

    for goal in goals:
        revenue_tasks.append(f"Execute a direct revenue action for: {goal}")
        skill_tasks.append(f"Improve a skill related to: {goal}")
        maintenance_tasks.append(f"Stabilize your environment for: {goal}")

    return {
        "Revenue Tasks (Do First)": revenue_tasks[:3],
        "Skill Tasks": skill_tasks[:3],
        "Maintenance Tasks": maintenance_tasks[:3],
    }


def print_daily_plan(tasks: dict[str, list[str]]) -> None:
    """Pretty-print the daily task plan."""
    print("\n" + "=" * 45)
    print("         ⚡ LIFE OS — TODAY'S TASK PLAN")
    print("=" * 45)

    for category, task_list in tasks.items():
        print(f"\n📌 {category}:")
        for i, task in enumerate(task_list, 1):
            print(f"   {i}. {task}")

    print("\n" + "=" * 45)
    print("Night Review Reminder: Answer your 4 questions.")
    print("=" * 45 + "\n")


if __name__ == "__main__":
    # ✏️ Edit your active goals here
    goals = ["business growth", "physical fitness", "skill development"]

    tasks = generate_tasks(goals)
    print_daily_plan(tasks)
