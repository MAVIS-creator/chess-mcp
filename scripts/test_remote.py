from __future__ import annotations

import argparse
import asyncio

from fastmcp import Client


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="Full MCP URL, e.g. https://service.run.app/mcp")
    args = parser.parse_args()

    async with Client(args.url) as client:
        tools = await client.list_tools()
        print("Tools:")
        for tool in tools:
            print(" -", tool.name)
        result = await client.call_tool(
            "analyze_position",
            {
                "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                "time_ms": 500,
                "multipv": 2,
            },
        )
        print("\nAnalysis result:")
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
