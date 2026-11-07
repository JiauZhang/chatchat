"""Where a sub-agent runs when it must not touch the checked-out tree."""

import asyncio

from chatchat.runtime.sandbox import Sandbox


def test_without_a_provider_there_is_no_sandbox():
    async def main():
        try:
            await Sandbox().reserve("side", "reader@team")
        except ValueError as exc:
            return str(exc)
        return ""

    assert "sandbox needs a provider" in asyncio.run(main())


def test_a_reserved_directory_is_handed_back_to_the_provider():
    handed_back = []

    async def start(name):
        return f"/tmp/{name}"

    async def end(path):
        handed_back.append(path)
        return f"kept {path}"

    async def main():
        sandbox = Sandbox(start=start, end=end)
        path = await sandbox.reserve("side", "reader@team")
        return path, await sandbox.release("reader@team"), await sandbox.release("reader@team")

    path, note, again = asyncio.run(main())
    assert path == "/tmp/side"
    assert note == "kept /tmp/side"
    assert again == ""
    assert handed_back == ["/tmp/side"]


def test_a_provider_that_only_starts_leaves_the_directory_alone():
    async def start(name):
        return f"/tmp/{name}"

    async def main():
        sandbox = Sandbox(start=start)
        await sandbox.reserve("side", "reader@team")
        return await sandbox.release("reader@team")

    assert asyncio.run(main()) == ""
