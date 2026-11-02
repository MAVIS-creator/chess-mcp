from __future__ import annotations

import argparse
import asyncio

from fastmcp import Client


STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="Full MCP URL, e.g. https://service.run.app/mcp")
    args = parser.parse_args()

    async with Client(args.url) as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools}
        print("Tools:")
        for tool in tools:
            print(" -", tool.name)

        required = {"engine_status", "validate_position", "adaptive_analysis", "analyze_position"}
        missing = required - names
        if missing:
            raise RuntimeError(f"Missing expected MCP tools: {sorted(missing)}")

        status = await client.call_tool("engine_status", {})
        print("\nEngine status:")
        print(status)

        result = await client.call_tool(
            "adaptive_analysis",
            {
                "fen": STARTING_FEN,
                "profile": "quick",
            },
        )
        print("\nAdaptive analysis result:")
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
