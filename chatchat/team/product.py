from __future__ import annotations


class TeamProduct:
    """What a host puts on a team: the behaviour the runtime triggers but does not own.

    The runtime knows when the working directory moved, when the permission
    mode changed and when a skill handed itself more tools. What that means is
    the product's business - chdir, reload the project rules, move a permission
    gate - so a product implements the methods it cares about and ignores the
    rest. This is the only place a host hangs itself on a team.
    """

    def cwd_changed(self, cwd) -> None:
        pass

    def plan_mode_changed(self, mode: str) -> None:
        pass

    def skills_granted(self, tools) -> None:
        pass
