from __future__ import annotations

import argparse
import asyncio

from fastmcp import Client


STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
TABLEBASE_FEN = "8/4K2k/5Q1P/6P1/8/8/q7/8 w - - 99 148"


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

        required = {
            "engine_status",
            "validate_position",
            "full_analysis",
            "adaptive_analysis",
            "opening_context",
            "tablebase_lookup",
            "player_history",
            "record_player_event",
            "analyze_position",
        }
        missing = required - names
        if missing:
            raise RuntimeError(f"Missing expected MCP tools: {sorted(missing)}")

        status = await client.call_tool("engine_status", {})
        print("\nEngine status:")
        print(status)

        result = await client.call_tool(
            "full_analysis",
            {
                "fen": STARTING_FEN,
                "profile": "quick",
                "max_total_ms": 6000,
            },
        )
        print("\nFull analysis result:")
        print(result)

        tablebase = await client.call_tool("tablebase_lookup", {"fen": TABLEBASE_FEN})
        print("\nTablebase result:")
        print(tablebase)


if __name__ == "__main__":
    asyncio.run(main())
