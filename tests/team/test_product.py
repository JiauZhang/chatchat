"""The one place a host hangs itself on a team, and what happens without one."""

import asyncio
from pathlib import Path

from helpers import RecordingProduct, mock_team

from chatchat.runtime.skills import Skill
from chatchat.tool import ToolContext
from chatchat.tools.builtin import skills as skill_tools


def test_attaching_a_product_hands_it_back():
    async def main():
        team = mock_team("p1")
        product = RecordingProduct()
        return team.attach(product) is product, team.product is product

    assert asyncio.run(main()) == (True, True)


def test_a_team_without_a_product_still_switches_mode_on_the_hooks():
    async def main():
        team = mock_team("p2")
        team.set_plan_mode("plan")
        return team.hooks.permission_mode

    assert asyncio.run(main()) == "plan"


def test_moving_the_directory_tells_the_product():
    async def main():
        team = mock_team("p3", tool_context=ToolContext(cwd=Path(".")))
        product = team.attach(RecordingProduct())
        team.set_cwd("/tmp/elsewhere")
        return product.cwds

    assert asyncio.run(main()) == [Path("/tmp/elsewhere")]


def test_a_skill_that_grants_tools_tells_the_product():
    async def main():
        team = mock_team("p4")
        product = team.attach(RecordingProduct())
        team.skills.register(Skill(name="grants", description="d", body_text="b", allowed_tools=("Read",)))
        await skill_tools.use_skill(None, team=team, agent=team.lead, input={"skill": "grants"})
        return product.granted

    assert asyncio.run(main()) == [("Read",)]


def test_a_skill_that_grants_tools_without_a_product_is_harmless():
    async def main():
        team = mock_team("p5")
        team.skills.register(Skill(name="grants", description="d", body_text="b", allowed_tools=("Read",)))
        return await skill_tools.use_skill(None, team=team, agent=team.lead, input={"skill": "grants"})

    assert asyncio.run(main()) == "b"
