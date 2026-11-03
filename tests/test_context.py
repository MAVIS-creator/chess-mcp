import chess

from app.context import context_service, position_key


def test_position_key_ignores_move_counters():
    first = "8/8/8/8/8/8/6K1/7k w - - 0 1"
    second = "8/8/8/8/8/8/6K1/7k w - - 42 99"
    assert position_key(first) == position_key(second)


def test_local_opening_recognizes_sicilian():
    board = chess.Board()
    board.push_san("e4")
    board.push_san("c5")
    result = context_service.local_opening(board.fen())
    assert result["available"] is True
    assert result["name"] == "Sicilian Defense"


def test_tablebase_skips_positions_with_more_than_seven_pieces():
    result = context_service.tablebase_context(chess.STARTING_FEN)
    assert result["applicable"] is False
    assert result["piece_count"] == 32


def test_history_without_player_is_non_blocking():
    result = context_service.history_context(None, chess.STARTING_FEN)
    assert result["provided"] is False
    assert result["events"] == []
