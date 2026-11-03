import pytest

from app.visual import (
    compare_visual_fens,
    validate_visual_reconstruction,
)

STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
AFTER_E4_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
AFTER_E4_WRONG_EP_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
AFTER_E4_WRONG_CASTLING_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b - e3 0 1"


def test_visual_reconstruction_blocks_low_confidence() -> None:
    result = validate_visual_reconstruction(
        STARTING_FEN,
        recognition_confidence=0.72,
        side_to_move_confirmed=True,
        orientation="white_bottom",
    )
    assert result["analysis_ready"] is False
    assert result["blockers"]


def test_visual_reconstruction_blocks_unconfirmed_turn_or_ambiguity() -> None:
    result = validate_visual_reconstruction(
        STARTING_FEN,
        recognition_confidence=0.99,
        side_to_move_confirmed=False,
        orientation="white_bottom",
        ambiguity_notes=["Piece on g1 is unclear"],
    )
    assert result["analysis_ready"] is False
    assert len(result["blockers"]) == 2


def test_visual_reconstruction_allows_confident_position() -> None:
    result = validate_visual_reconstruction(
        STARTING_FEN,
        recognition_confidence=0.99,
        side_to_move_confirmed=True,
        orientation="white_bottom",
    )
    assert result["analysis_ready"] is True
    assert result["turn"] == "white"


def test_visual_reconstruction_preserves_exact_en_passant_state() -> None:
    result = validate_visual_reconstruction(
        AFTER_E4_FEN,
        recognition_confidence=0.99,
        side_to_move_confirmed=True,
        orientation="white_bottom",
    )
    assert " e3 " in result["normalized_fen"]


def test_visual_reconstruction_bounds_ambiguity_notes() -> None:
    with pytest.raises(ValueError, match="at most 12 entries"):
        validate_visual_reconstruction(
            STARTING_FEN,
            recognition_confidence=0.99,
            side_to_move_confirmed=True,
            ambiguity_notes=["unclear"] * 13,
        )

    with pytest.raises(ValueError, match="at most 160 characters"):
        validate_visual_reconstruction(
            STARTING_FEN,
            recognition_confidence=0.99,
            side_to_move_confirmed=True,
            ambiguity_notes=["x" * 161],
        )


def test_compare_visual_fens_infers_e4() -> None:
    result = compare_visual_fens(STARTING_FEN, AFTER_E4_FEN)
    assert result["unique_legal_transition"] is True
    assert result["inferred_move"] == {"san": "e4", "uci": "e2e4"}
    assert {change["square"] for change in result["changed_squares"]} == {"e2", "e4"}


def test_compare_visual_fens_rejects_wrong_en_passant_state() -> None:
    result = compare_visual_fens(STARTING_FEN, AFTER_E4_WRONG_EP_FEN)
    assert result["unique_legal_transition"] is False
    assert result["inferred_move"] is None


def test_compare_visual_fens_rejects_wrong_castling_state() -> None:
    result = compare_visual_fens(STARTING_FEN, AFTER_E4_WRONG_CASTLING_FEN)
    assert result["unique_legal_transition"] is False
    assert result["inferred_move"] is None
