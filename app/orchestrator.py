from __future__ import annotations

import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from app.context import context_service
from app.engine import AnalysisProfile, service

MAX_FULL_ANALYSIS_MS = 28000
DEFAULT_FULL_ANALYSIS_MS = 25000


def _score_gap_cp(lines: list[dict[str, Any]]) -> int | None:
    if len(lines) < 2:
        return None
    first = (lines[0].get("score") or {}).get("numeric_for_sorting")
    second = (lines[1].get("score") or {}).get("numeric_for_sorting")
    if first is None or second is None:
        return None
    return int(first) - int(second)


def adaptive_engine_analysis(
    fen: str,
    *,
    profile: AnalysisProfile = "normal",
    close_gap_cp: int = 35,
    allow_confirmation: bool = True,
) -> dict[str, Any]:
    settings = service.profile_settings(profile)
    initial = service.analyze(
        fen,
        time_ms=settings["initial_time_ms"],
        multipv=settings["multipv"],
    )
    lines = initial["lines"]
    gap_cp = _score_gap_cp(lines)
    forced_mate = bool(lines and (lines[0].get("score") or {}).get("mate_in") is not None)
    confirmation = None
    threshold = max(0, min(int(close_gap_cp), 300))
    reason = "initial search was decisive enough"

    if allow_confirmation and not forced_mate and gap_cp is not None and gap_cp <= threshold:
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


def _future_value(future: Future[dict[str, Any]], fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        return future.result(timeout=0)
    except Exception:  # noqa: BLE001 - optional provider failure must degrade gracefully
        return fallback


def _tablebase_recommendation(tablebase: dict[str, Any]) -> dict[str, Any] | None:
    if not tablebase.get("exact"):
        return None
    moves = tablebase.get("moves") or []
    if not moves:
        return {
            "source": "syzygy",
            "move": None,
            "move_uci": None,
            "category": tablebase.get("category"),
            "reason": "Syzygy gives the exact game-theoretic result for this position.",
        }
    first = moves[0]
    return {
        "source": "syzygy",
        "move": first.get("san"),
        "move_uci": first.get("uci"),
        "category": tablebase.get("category"),
        "dtz": first.get("dtz"),
        "dtm": first.get("dtm"),
        "reason": "Syzygy tablebase is exact and overrides heuristic engine evaluation.",
    }


def full_chess_analysis(
    fen: str,
    *,
    profile: AnalysisProfile = "normal",
    player_id: str | None = None,
    close_gap_cp: int = 35,
    max_total_ms: int = DEFAULT_FULL_ANALYSIS_MS,
) -> dict[str, Any]:
    """Run the complete low-latency chess pipeline.

    Opening/game context, Syzygy and player history begin immediately in parallel while Stockfish
    performs the objective calculation. The function keeps optional context advisory and makes an
    exact tablebase result authoritative when available.
    """
    started = time.monotonic()
    budget_ms = max(3000, min(int(max_total_ms), MAX_FULL_ANALYSIS_MS))
    board = service.board_from_fen(fen)
    normalized_fen = board.fen()

    network_timeout_ms = min(1500, max(400, budget_ms // 10))
    executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="chess-context")
    opening_future = executor.submit(
        context_service.opening_context,
        normalized_fen,
        network_timeout_ms,
    )
    tablebase_future = executor.submit(
        context_service.tablebase_context,
        normalized_fen,
        network_timeout_ms,
    )
    history_future = executor.submit(
        context_service.history_context,
        player_id,
        normalized_fen,
    )

    settings = service.profile_settings(profile)
    initial = service.analyze(
        normalized_fen,
        time_ms=settings["initial_time_ms"],
        multipv=settings["multipv"],
    )

    tablebase = _future_value(
        tablebase_future,
        {"available": False, "exact": False, "pending_or_failed": True},
    )
    lines = initial["lines"]
    gap_cp = _score_gap_cp(lines)
    threshold = max(0, min(int(close_gap_cp), 300))
    forced_mate = bool(lines and (lines[0].get("score") or {}).get("mate_in") is not None)
    confirmation = None
    confirmation_reason = "initial search was decisive enough"

    elapsed_ms = int((time.monotonic() - started) * 1000)
    remaining_ms = budget_ms - elapsed_ms
    exact_tablebase = bool(tablebase.get("exact"))

    if (
        not exact_tablebase
        and not forced_mate
        and gap_cp is not None
        and gap_cp <= threshold
        and remaining_ms >= settings["confirm_time_ms"] + 500
    ):
        candidates = [line.get("move_uci") for line in lines[:2] if line.get("move_uci")]
        if len(candidates) >= 2:
            confirmation = service.analyze(
                normalized_fen,
                time_ms=min(settings["confirm_time_ms"], max(500, remaining_ms - 400)),
                multipv=len(candidates),
                root_moves=[str(move) for move in candidates],
            )
            confirmation_reason = (
                "top engine candidates were close, so the remaining budget was used to confirm them"
            )
    elif exact_tablebase:
        confirmation_reason = "exact Syzygy result was available, so deeper engine confirmation was skipped"
    elif remaining_ms < settings["confirm_time_ms"] + 500:
        confirmation_reason = "latency budget was preserved instead of starting another deep search"

    final_engine = confirmation or initial

    opening = _future_value(
        opening_future,
        {"available": False, "pending_or_failed": True},
    )
    if not tablebase.get("available") and not tablebase.get("applicable") is False:
        tablebase = _future_value(
            tablebase_future,
            tablebase,
        )
    history = _future_value(
        history_future,
        {"enabled": context_service.history.enabled, "events": [], "pending_or_failed": True},
    )
    executor.shutdown(wait=False, cancel_futures=True)

    tablebase_pick = _tablebase_recommendation(tablebase)
    if tablebase_pick is not None:
        recommendation = tablebase_pick
        authoritative_source = "syzygy"
    else:
        final_lines = final_engine.get("lines") or []
        best = final_lines[0] if final_lines else {}
        recommendation = {
            "source": "stockfish",
            "move": best.get("move"),
            "move_uci": best.get("move_uci"),
            "score": best.get("score"),
            "reason": "Stockfish provided the strongest calculated move within the latency budget.",
        }
        authoritative_source = "stockfish"

    total_ms = int((time.monotonic() - started) * 1000)
    return {
        "fen": normalized_fen,
        "profile": profile,
        "latency": {
            "budget_ms": budget_ms,
            "elapsed_ms": total_ms,
            "within_budget": total_ms <= budget_ms,
            "network_context_timeout_ms": network_timeout_ms,
        },
        "authoritative_source": authoritative_source,
        "recommendation": recommendation,
        "engine": {
            "initial": initial,
            "confirmation": confirmation,
            "final": final_engine,
            "initial_top_two_gap_cp": gap_cp,
            "close_gap_threshold_cp": threshold,
            "confirmation_reason": confirmation_reason,
        },
        "opening_and_games": opening,
        "tablebase": tablebase,
        "player_history": history,
        "model_guidance": {
            "objective_priority": ["syzygy_when_exact", "stockfish", "opening_statistics"],
            "personalization_rule": (
                "Use player history to tailor explanations and training advice, never to override "
                "an exact tablebase result or Stockfish's objective calculation."
            ),
        },
    }
