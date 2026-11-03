from __future__ import annotations

import argparse
import asyncio
import os

from fastmcp import Client
from fastmcp.client.auth import BearerAuth

STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
AFTER_E4_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
TABLEBASE_FEN = "8/4K2k/5Q1P/6P1/8/8/q7/8 w - - 99 148"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="Full MCP URL, e.g. https://service.run.app/mcp")
    args = parser.parse_args()
    token = os.getenv("MCP_AUTH_TOKEN")
    if not token:
        parser.error("Set MCP_AUTH_TOKEN to the deployed bearer token.")

    async with Client(args.url, auth=BearerAuth(token)) as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools}
        print("Tools:")
        for tool in tools:
            print(" -", tool.name)

        required = {
            "engine_status",
            "validate_position",
            "full_analysis",
            "analyze_visual_position",
            "compare_visual_positions",
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

        visual = await client.call_tool(
            "analyze_visual_position",
            {
                "fen": STARTING_FEN,
                "recognition_confidence": 0.99,
                "side_to_move_confirmed": True,
                "orientation": "white_bottom",
                "profile": "quick",
                "max_total_ms": 6000,
            },
        )
        print("\nVisual-position analysis result:")
        print(visual)

        visual_diff = await client.call_tool(
            "compare_visual_positions",
            {
                "before_fen": STARTING_FEN,
                "after_fen": AFTER_E4_FEN,
                "before_recognition_confidence": 0.99,
                "after_recognition_confidence": 0.99,
                "before_side_to_move_confirmed": True,
                "after_side_to_move_confirmed": True,
                "before_orientation": "white_bottom",
                "after_orientation": "white_bottom",
            },
        )
        print("\nVisual-position diff result:")
        print(visual_diff)

        tablebase = await client.call_tool("tablebase_lookup", {"fen": TABLEBASE_FEN})
        print("\nTablebase result:")
        print(tablebase)


if __name__ == "__main__":
    asyncio.run(main())
