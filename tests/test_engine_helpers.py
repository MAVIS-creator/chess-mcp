import chess
import pytest

from app.engine import StockfishService


def test_valid_starting_position():
    board = StockfishService.board_from_fen(chess.STARTING_FEN)
    assert board.turn == chess.WHITE
    assert board.is_valid()


def test_invalid_fen_rejected():
    with pytest.raises(ValueError):
        StockfishService.board_from_fen("not a fen")


def test_parse_san_and_uci():
    board = chess.Board()
    assert StockfishService.parse_move(board, "e4").uci() == "e2e4"
    assert StockfishService.parse_move(board, "e2e4").uci() == "e2e4"


def test_illegal_move_rejected():
    board = chess.Board()
    with pytest.raises(ValueError):
        StockfishService.parse_move(board, "e2e5")


def test_analysis_profiles_are_cost_bounded():
    quick = StockfishService.profile_settings("quick")
    normal = StockfishService.profile_settings("normal")
    deep = StockfishService.profile_settings("deep")

    assert quick["initial_time_ms"] < normal["initial_time_ms"] < deep["initial_time_ms"]
    assert quick["confirm_time_ms"] < normal["confirm_time_ms"] < deep["confirm_time_ms"]
    assert quick["multipv"] <= normal["multipv"] <= deep["multipv"]


def test_unknown_analysis_profile_rejected():
    with pytest.raises(ValueError):
        StockfishService.profile_settings("ultra")  # type: ignore[arg-type]
