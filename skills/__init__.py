"""
Skills registry.

Each skill is a Python module with:
    TRIGGERS: list[str]   — phrases that activate this skill
    PROMPT: str           — coaching instructions injected into the system prompt

load_all_skills() assembles all active skills into a single SKILL RESPONSES block.
To add a new skill: drop a new .py file in nutrition/ or fitness/ with TRIGGERS + PROMPT.
To disable a skill: set ENABLED = False in that file.
"""

import importlib
import pkgutil
from pathlib import Path


def _load_module_skills(package_path: str, package_name: str) -> list[tuple[str, str, str]]:
    """
    Load all skill modules from a package directory.
    Returns list of (skill_name, triggers_str, prompt_str).
    """
    skills = []
    pkg_dir = Path(package_path)

    for _, module_name, _ in pkgutil.iter_modules([str(pkg_dir)]):
        if module_name.startswith("_"):
            continue
        full_name = f"{package_name}.{module_name}"
        try:
            mod = importlib.import_module(full_name)
        except ImportError as e:
            import logging
            logging.getLogger(__name__).warning(f"Could not load skill {full_name}: {e}")
            continue

        if getattr(mod, "ENABLED", True) is False:
            continue

        triggers = getattr(mod, "TRIGGERS", [])
        prompt = getattr(mod, "PROMPT", "")

        if triggers and prompt:
            display_name = module_name.upper().replace("_", " ")
            skills.append((display_name, triggers, prompt))

    return skills


def load_all_skills() -> str:
    """
    Assemble all skill prompts into a single SKILL RESPONSES block
    for injection into the system prompt.
    """
    base_dir = Path(__file__).parent

    all_skills = []

    # Base skills (always loaded — food + exercise core logic is in prompts/arnie.py)
    # Nutrition skills
    all_skills += _load_module_skills(
        str(base_dir / "nutrition"), "skills.nutrition"
    )
    # Fitness skills
    all_skills += _load_module_skills(
        str(base_dir / "fitness"), "skills.fitness"
    )

    if not all_skills:
        return ""

    lines = [
        "SKILL KNOWLEDGE: domain expertise to draw on when these intents come up.\n"
        "These give you the WHAT: the facts, what to cover, what to prioritize. They do NOT\n"
        "change HOW you talk. Your normal voice still governs every reply: deliver all of it\n"
        "in your usual sentence-case, multi-bubble texting voice, lead with the read then the\n"
        "next move, never as a report, list, or template.\n"
    ]
    for name, triggers, prompt in all_skills:
        trigger_str = ", ".join(f'"{t}"' for t in triggers[:4])
        lines.append(f"▸ {name}  triggers: {trigger_str}")
        lines.append(f"  {prompt.strip()}")
        lines.append("")

    return "\n".join(lines).strip()
