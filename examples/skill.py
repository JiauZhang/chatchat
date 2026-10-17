import argparse
import asyncio
from pathlib import Path

from chatchat.runtime.skills import SkillRegistry
from chatchat.team.team import Team

NOTES = """---
name: notes
description: turn a rough log into bullets
when_to_use: the material is meeting notes or a changelog
---

Rewrite the material as three to five imperative bullets.
Keep decisions and actions, drop commentary.
"""


def registry_for(root: Path) -> SkillRegistry:
    directory = root / "skills" / "notes"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(NOTES, encoding="utf-8")
    return SkillRegistry.load([(directory.parent, "project")])


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--prompt", default="Turn this into bullets: we met, decided to ship Friday, Ana owns the migration.")
    parser.add_argument("--mock", action="store_true", help="load the skill without calling a model")
    args = parser.parse_args()

    root = Path(".skill-demo").resolve()
    registry = registry_for(root)
    print("discovered:", [skill.name for skill in registry.all()])
    if args.mock:
        print("---- body loaded on demand ----")
        print(registry.get("notes").render(args.prompt))
        return
    team = Team(
        "skill",
        provider=args.provider,
        model=args.model,
        lead_instruction="Use the notes skill when the material looks like meeting notes.",
        skills=registry,
    )
    print(await team.query(args.prompt))


if __name__ == "__main__":
    asyncio.run(main())
