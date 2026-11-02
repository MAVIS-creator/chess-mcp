from __future__ import annotations

import atexit
import os
from typing import Literal

import chess
import chess.engine
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.engine import AnalysisProfile, service

mcp = FastMCP(
    "ChatGPT Stockfish",
    instructions=(
        "Use these tools for objective chess calculation. Prefer adaptive_analysis for normal "
        "position analysis because it starts cheaply and only spends more compute when candidate "
        "moves are close. Use analyze_position for a fixed search, compare_moves when specific "
        "candidate moves matter, and analyze_move to audit a move. Scores are always reported "
        "from the side-to-move perspective in the supplied FEN."
    ),
)


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    try:
        data = service.status()
        return JSONResponse({"status": "ok", "engine": data.get("engine_id", {})})
    except (OSError, chess.engine.EngineError) as exc:
        return JSONResponse({"status": "error", "detail": str(exc)}, status_code=503)


@mcp.tool
def validate_position(fen: str) -> dict:
    """Validate a FEN and return basic position facts plus legal moves.

    Useful after converting a board image to FEN before asking Stockfish to search.
    """
    board = service.board_from_fen(fen)
    legal = []
    for move in board.legal_moves:
        legal.append({"san": board.san(move), "uci": move.uci()})
    return {
        "valid": True,
        "normalized_fen": board.fen(),
        "turn": "white" if board.turn == chess.WHITE else "black",
        "in_check": board.is_check(),
        "checkmate": board.is_checkmate(),
        "stalemate": board.is_stalemate(),
        "legal_moves": legal,
    }


@mcp.tool
def analyze_position(
    fen: str,
    time_ms: int = 1500,
    multipv: int = 3,
    depth: int | None = None,
    nodes: int | None = None,
) -> dict:
    """Analyze a chess position with Stockfish and return ranked principal variations.

    time_ms controls wall-clock search time. multipv controls how many candidate lines are returned.
    depth and nodes are optional additional limits; server-side caps prevent runaway compute.
    """
    return service.analyze(
        fen,
        time_ms=time_ms,
        multipv=multipv,
        depth=depth,
        nodes=nodes,
    )


@mcp.tool
def adaptive_analysis(
    fen: str,
    profile: AnalysisProfile = "normal",
    close_gap_cp: int = 35,
) -> dict:
    """Analyze efficiently, deepening only when the best candidate moves are close.

    Profiles are quick, normal, and deep. The first pass is deliberately inexpensive. If the top
    two engine moves are within close_gap_cp centipawns and there is no forced mate, the tool
    rechecks those two candidates with a longer restricted search. This usually gives a stronger
    answer without paying deep-search cost on obvious positions.
    """
    settings = service.profile_settings(profile)
    initial = service.analyze(
        fen,
        time_ms=settings["initial_time_ms"],
        multipv=settings["multipv"],
    )
    lines = initial["lines"]

    gap_cp = None
    forced_mate = False
    if lines:
        forced_mate = (lines[0].get("score") or {}).get("mate_in") is not None
    if len(lines) >= 2:
        first = (lines[0].get("score") or {}).get("numeric_for_sorting")
        second = (lines[1].get("score") or {}).get("numeric_for_sorting")
        if first is not None and second is not None:
            gap_cp = int(first) - int(second)

    confirmation = None
    reason = "initial search was decisive enough"
    threshold = max(0, min(int(close_gap_cp), 300))

    if not forced_mate and gap_cp is not None and gap_cp <= threshold:
        candidates = [line.get("move_uci") for line in lines[:2] if line.get("move_uci")]
        if len(candidates) >= 2:
            confirmation = service.analyze(
                fen,
                time_ms=settings["confirm_time_ms"],
                multipv=len(candidates),
                root_moves=[str(move) for move in candidates],
            )
            reason = "top moves were close, so a deeper restricted confirmation search was run"

    final = confirmation or initial
    return {
        "profile": profile,
        "profile_settings": settings,
        "close_gap_threshold_cp": threshold,
        "initial_top_two_gap_cp": gap_cp,
        "used_confirmation_search": confirmation is not None,
        "decision_reason": reason,
        "initial": initial,
        "confirmation": confirmation,
        "final": final,
    }


@mcp.tool
def compare_moves(fen: str, moves: list[str], time_ms: int = 2000) -> dict:
    """Compare specific legal candidate moves using one restricted Stockfish search.

    Moves may be supplied in SAN (Nf5, Bxh7+) or UCI (g1f3). Results are ranked from the
    current side-to-move perspective. Comparing them in one MultiPV search is fairer and cheaper
    than running a separate full search for every candidate.
    """
    return service.compare_moves(fen, moves, time_ms=time_ms)


@mcp.tool
def analyze_move(fen: str, move: str, time_ms: int = 2000) -> dict:
    """Audit one move against Stockfish's best move from the same position."""
    board = service.board_from_fen(fen)
    played = service.parse_move(board, move)
    best = service.analyze(fen, time_ms=time_ms, multipv=1)
    played_line = service.analyze(
        fen,
        time_ms=time_ms,
        multipv=1,
        root_moves=[played.uci()],
    )

    best_score = best["lines"][0].get("score") or {}
    played_score = played_line["lines"][0].get("score") or {}
    best_numeric = best_score.get("numeric_for_sorting")
    played_numeric = played_score.get("numeric_for_sorting")
    loss_cp = None
    if best_numeric is not None and played_numeric is not None:
        loss_cp = max(0, int(best_numeric) - int(played_numeric))

    return {
        "fen": board.fen(),
        "played_move": board.san(played),
        "played_move_uci": played.uci(),
        "best": best["lines"][0],
        "played": played_line["lines"][0],
        "estimated_loss_centipawns": loss_cp,
    }


@mcp.tool
def tactical_scan(
    fen: str,
    time_ms: int = 3000,
    multipv: int = 5,
    mode: Literal["normal", "forcing"] = "forcing",
) -> dict:
    """Scan a position for forcing opportunities and tactical signals.

    The engine returns its strongest lines; the tool additionally reports whether there is a mate
    or a large evaluation gap between the best and second-best moves. The model should inspect the
    PVs to explain the actual motif rather than treating the signal as a named tactic.
    """
    analysis = service.analyze(fen, time_ms=time_ms, multipv=multipv)
    lines = analysis["lines"]
    mate_found = any((line.get("score") or {}).get("mate_in") is not None for line in lines)
    gap_cp = None
    if len(lines) >= 2:
        first = (lines[0].get("score") or {}).get("numeric_for_sorting")
        second = (lines[1].get("score") or {}).get("numeric_for_sorting")
        if first is not None and second is not None:
            gap_cp = int(first) - int(second)

    return {
        **analysis,
        "scan_mode": mode,
        "signals": {
            "forced_mate_in_top_lines": mate_found,
            "best_vs_second_gap_centipawns": gap_cp,
            "large_best_move_gap": gap_cp is not None and gap_cp >= 150,
        },
    }


@mcp.tool
def engine_status() -> dict:
    """Return Stockfish version/configuration, analysis profiles, and server safety limits."""
    return service.status()


atexit.register(service.close)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=port,
        path="/mcp",
        stateless_http=True,
    )
