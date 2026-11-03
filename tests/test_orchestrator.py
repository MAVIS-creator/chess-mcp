import chess

from app import orchestrator


def _fake_engine_result(move: str = "e4") -> dict:
    board = chess.Board()
    parsed = board.parse_san(move)
    return {
        "fen": board.fen(),
        "turn": "white",
        "in_check": False,
        "fullmove_number": 1,
        "best_move": move,
        "best_move_uci": parsed.uci(),
        "lines": [
            {
                "move": move,
                "move_uci": parsed.uci(),
                "score": {"numeric_for_sorting": 30, "centipawns": 30},
                "pv": {"san": [move], "uci": [parsed.uci()]},
            },
            {
                "move": "d4",
                "move_uci": "d2d4",
                "score": {"numeric_for_sorting": 20, "centipawns": 20},
                "pv": {"san": ["d4"], "uci": ["d2d4"]},
            },
        ],
    }


def test_exact_tablebase_is_authoritative(monkeypatch):
    monkeypatch.setattr(
        orchestrator.service,
        "profile_settings",
        lambda profile: {"initial_time_ms": 50, "confirm_time_ms": 50, "multipv": 2},
    )
    monkeypatch.setattr(orchestrator.service, "analyze", lambda *args, **kwargs: _fake_engine_result())
    monkeypatch.setattr(
        orchestrator.context_service,
        "opening_context",
        lambda fen, timeout_ms: {"available": True, "name": "Test Opening"},
    )
    monkeypatch.setattr(
        orchestrator.context_service,
        "tablebase_context",
        lambda fen, timeout_ms: {
            "applicable": True,
            "available": True,
            "exact": True,
            "category": "win",
            "moves": [{"san": "Qg7#", "uci": "f6g7", "dtz": 1, "dtm": 1}],
        },
    )
    monkeypatch.setattr(
        orchestrator.context_service,
        "history_context",
        lambda player_id, fen: {"enabled": True, "exact_position_events": []},
    )

    fen = "8/4K2k/5Q1P/6P1/8/8/q7/8 w - - 99 148"
    result = orchestrator.full_chess_analysis(fen, profile="quick", player_id="victor")

    assert result["authoritative_source"] == "syzygy"
    assert result["recommendation"]["move"] == "Qg7#"
    assert result["engine"]["confirmation"] is None
    assert result["latency"]["within_budget"] is True


def test_stockfish_remains_authoritative_without_exact_tablebase(monkeypatch):
    monkeypatch.setattr(
        orchestrator.service,
        "profile_settings",
        lambda profile: {"initial_time_ms": 50, "confirm_time_ms": 50, "multipv": 2},
    )
    monkeypatch.setattr(orchestrator.service, "analyze", lambda *args, **kwargs: _fake_engine_result())
    monkeypatch.setattr(
        orchestrator.context_service,
        "opening_context",
        lambda fen, timeout_ms: {"available": False},
    )
    monkeypatch.setattr(
        orchestrator.context_service,
        "tablebase_context",
        lambda fen, timeout_ms: {"applicable": False, "available": False, "exact": False},
    )
    monkeypatch.setattr(
        orchestrator.context_service,
        "history_context",
        lambda player_id, fen: {"enabled": False, "events": []},
    )

    result = orchestrator.full_chess_analysis(chess.STARTING_FEN, profile="quick")

    assert result["authoritative_source"] == "stockfish"
    assert result["recommendation"]["move"] == "e4"
