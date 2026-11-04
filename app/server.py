from __future__ import annotations

import atexit
import os
from typing import Literal

import chess
import chess.engine
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.auth import EnvironmentTokenVerifier
from app.context import context_service
from app.engine import AnalysisProfile, service
from app.orchestrator import adaptive_engine_analysis, full_chess_analysis
from app.visual import Orientation, compare_visual_fens, validate_visual_reconstruction

mcp = FastMCP(
    "ChatGPT Stockfish",
    auth=EnvironmentTokenVerifier(),
    instructions=(
        "Prefer full_analysis for normal chess questions: it combines Stockfish, opening/game "
        "context, Syzygy and optional player history under a strict latency budget. Use "
        "adaptive_analysis when only engine calculation is needed, analyze_position for a fixed "
        "search, compare_moves for named candidates, and analyze_move to audit a move. Exact "
        "Syzygy results outrank heuristic engine evaluations. Player history may personalize the "
        "explanation but must never override objective calculation. Scores are reported from the "
        "side-to-move perspective in the supplied FEN. When the user supplies a chess-board image, "
        "use the host's vision capability to reconstruct a full FEN, determine board orientation, "
        "and confirm whose turn it is, then call analyze_visual_position. Never guess through an "
        "unclear square, unknown castling/en-passant state, or uncertain side to move: lower "
        "recognition_confidence and describe every uncertainty in ambiguity_notes so the tool can "
        "stop before engine analysis. For before/after board images, reconstruct and validate both "
        "positions, then call compare_visual_positions with confidence and ambiguity metadata for "
        "each image before giving conclusions."
    ),
)


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    try:
        data = service.status()
        return JSONResponse(
            {
                "status": "ok",
                "engine": data.get("engine_id", {}),
                "history_enabled": context_service.history.enabled,
            }
        )
    except (OSError, chess.engine.EngineError) as exc:
        return JSONResponse({"status": "error", "detail": str(exc)}, status_code=503)


@mcp.custom_route("/api/analyze", methods=["POST"])
async def cedar_browser_analyze(request: Request) -> JSONResponse:
    """Authenticated fixed-budget Stockfish route for the Cedar Chess web client."""
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    token = authorization[7:].strip()
    if not token or await EnvironmentTokenVerifier().verify_token(token) is None:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    if not isinstance(payload, dict):
        return JSONResponse({"error": "Invalid request body"}, status_code=400)

    fen = payload.get("fen")
    if not isinstance(fen, str) or not fen.strip() or len(fen) > 120:
        return JSONResponse({"error": "A valid FEN is required"}, status_code=400)

    def optional_int(name: str, default: int | None = None) -> int | None:
        value = payload.get(name, default)
        if value is None:
            return None
        if isinstance(value, bool):
            raise TypeError(f"{name} must be an integer")
        return int(value)

    try:
        analysis = service.analyze(
            fen.strip(),
            time_ms=optional_int("time_ms", 1200) or 1200,
            multipv=optional_int("multipv", 3) or 3,
            depth=optional_int("depth"),
            nodes=optional_int("nodes"),
        )
        return JSONResponse({**analysis, "engine_source": "gcp-stockfish-19"})
    except (TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except (OSError, chess.engine.EngineError) as exc:
        return JSONResponse({"error": "Engine unavailable", "detail": str(exc)}, status_code=503)


@mcp.custom_route("/api/tablebase", methods=["POST"])
async def cedar_browser_tablebase(request: Request) -> JSONResponse:
    """Authenticated exact Syzygy endgame context for Cedar Chess gameplay."""
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    token = authorization[7:].strip()
    if not token or await EnvironmentTokenVerifier().verify_token(token) is None:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    if not isinstance(payload, dict):
        return JSONResponse({"error": "Invalid request body"}, status_code=400)

    fen = payload.get("fen")
    if not isinstance(fen, str) or not fen.strip() or len(fen) > 120:
        return JSONResponse({"error": "A valid FEN is required"}, status_code=400)

    try:
        board = service.board_from_fen(fen.strip())
        if len(board.piece_map()) > 7:
            return JSONResponse({
                "applicable": False,
                "available": False,
                "exact": False,
                "piece_count": len(board.piece_map()),
            })

        result = context_service.tablebase_context(board.fen(), timeout_ms=1300)
        # Return only endgame information, never player-specific history.
        return JSONResponse(result)
    except ValueError:
        return JSONResponse({"error": "Invalid chess position"}, status_code=400)


@mcp.tool
def validate_position(fen: str) -> dict:
    """Validate a FEN and return basic position facts plus legal moves."""
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
def full_analysis(
    fen: str,
    profile: AnalysisProfile = "normal",
    player_id: str | None = None,
    close_gap_cp: int = 35,
    max_total_ms: int = 25000,
) -> dict:
    """Run the complete chess-brain pipeline with a hard latency budget.

    Opening/game context, Syzygy and optional player history run in parallel with Stockfish.
    Normal requests target a few seconds; max_total_ms is capped below the 30-second Cloud Run
    request ceiling. Use player_id when Firestore-backed personal history is enabled.
    """
    return full_chess_analysis(
        fen,
        profile=profile,
        player_id=player_id,
        close_gap_cp=close_gap_cp,
        max_total_ms=max_total_ms,
    )


@mcp.tool
def analyze_visual_position(
    fen: str,
    recognition_confidence: float,
    side_to_move_confirmed: bool,
    orientation: Orientation = "unknown",
    ambiguity_notes: list[str] | None = None,
    profile: AnalysisProfile = "normal",
    player_id: str | None = None,
    close_gap_cp: int = 35,
    max_total_ms: int = 25000,
) -> dict:
    """Validate and analyze a chess position reconstructed from an uploaded board image.

    The ChatGPT/host vision model should inspect the image and supply the reconstructed FEN.
    Set recognition_confidence conservatively, confirm whose move it is, and list any unclear
    squares, pieces, castling rights, or en-passant state in ambiguity_notes. The tool refuses
    engine analysis when the reconstruction is not reliable enough.
    """
    visual = validate_visual_reconstruction(
        fen,
        recognition_confidence=recognition_confidence,
        side_to_move_confirmed=side_to_move_confirmed,
        orientation=orientation,
        ambiguity_notes=ambiguity_notes,
    )
    if not visual["analysis_ready"]:
        return {
            "analysis_ready": False,
            "visual_validation": visual,
            "next_action": (
                "Re-check the uploaded board image or ask the user to clarify the ambiguous "
                "square(s), special position state, and side to move. Do not guess a best move yet."
            ),
        }

    analysis = full_chess_analysis(
        visual["normalized_fen"],
        profile=profile,
        player_id=player_id,
        close_gap_cp=close_gap_cp,
        max_total_ms=max_total_ms,
    )
    return {
        "analysis_ready": True,
        "visual_validation": visual,
        "analysis": analysis,
    }


@mcp.tool
def compare_visual_positions(
    before_fen: str,
    after_fen: str,
    before_recognition_confidence: float,
    after_recognition_confidence: float,
    before_side_to_move_confirmed: bool,
    after_side_to_move_confirmed: bool,
    before_orientation: Orientation = "unknown",
    after_orientation: Orientation = "unknown",
    before_ambiguity_notes: list[str] | None = None,
    after_ambiguity_notes: list[str] | None = None,
) -> dict:
    """Safely compare two image-reconstructed boards and infer a unique legal move.

    Both screenshot reconstructions must pass the same confidence, turn, and ambiguity safety
    checks as single-image analysis before transition inference is attempted.
    """
    before_visual = validate_visual_reconstruction(
        before_fen,
        recognition_confidence=before_recognition_confidence,
        side_to_move_confirmed=before_side_to_move_confirmed,
        orientation=before_orientation,
        ambiguity_notes=before_ambiguity_notes,
    )
    after_visual = validate_visual_reconstruction(
        after_fen,
        recognition_confidence=after_recognition_confidence,
        side_to_move_confirmed=after_side_to_move_confirmed,
        orientation=after_orientation,
        ambiguity_notes=after_ambiguity_notes,
    )

    if not before_visual["analysis_ready"] or not after_visual["analysis_ready"]:
        return {
            "comparison_ready": False,
            "before_visual_validation": before_visual,
            "after_visual_validation": after_visual,
            "next_action": (
                "Re-check both board images and resolve every ambiguity before inferring a move."
            ),
        }

    comparison = compare_visual_fens(
        before_visual["normalized_fen"],
        after_visual["normalized_fen"],
    )
    return {
        "comparison_ready": True,
        "before_visual_validation": before_visual,
        "after_visual_validation": after_visual,
        "comparison": comparison,
    }


@mcp.tool
def analyze_position(
    fen: str,
    time_ms: int = 1500,
    multipv: int = 3,
    depth: int | None = None,
    nodes: int | None = None,
) -> dict:
    """Analyze a chess position with a fixed Stockfish budget."""
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
    """Analyze efficiently, deepening only when the best engine candidates are close."""
    return adaptive_engine_analysis(
        fen,
        profile=profile,
        close_gap_cp=close_gap_cp,
    )


@mcp.tool
def opening_context(fen: str) -> dict:
    """Return fast local opening recognition plus authenticated master-game explorer data if set."""
    board = service.board_from_fen(fen)
    return context_service.opening_context(board.fen())


@mcp.tool
def tablebase_lookup(fen: str) -> dict:
    """Query exact Syzygy information for standard positions with seven or fewer pieces."""
    board = service.board_from_fen(fen)
    return context_service.tablebase_context(board.fen())


@mcp.tool
def player_history(player_id: str, fen: str) -> dict:
    """Return relevant personal chess-history context for a player and position."""
    board = service.board_from_fen(fen)
    return context_service.history_context(player_id, board.fen())


@mcp.tool
def record_player_event(
    player_id: str,
    fen: str,
    played_move: str | None = None,
    best_move: str | None = None,
    loss_cp: int | None = None,
    outcome: str | None = None,
    note: str | None = None,
) -> dict:
    """Store a bounded training/history event for future personalized analysis.

    This writes only to the configured Firestore history collection. It does not modify Stockfish
    or its NNUE network.
    """
    board = service.board_from_fen(fen)
    return context_service.history.record(
        player_id,
        board.fen(),
        played_move=played_move,
        best_move=best_move,
        loss_cp=loss_cp,
        outcome=outcome,
        note=note,
    )


@mcp.tool
def compare_moves(fen: str, moves: list[str], time_ms: int = 2000) -> dict:
    """Compare legal candidates in one restricted Stockfish MultiPV search."""
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
    """Scan a position for forcing opportunities and tactical signals."""
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
    return {
        **service.status(),
        "context": {
            "history_enabled": context_service.history.enabled,
            "tablebase_url": context_service.settings.tablebase_url,
            "opening_remote_enabled": bool(os.getenv("LICHESS_TOKEN")),
        },
    }


atexit.register(service.close)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=port,
        path="/mcp",
        stateless_http=True,
        json_response=True,
    )
