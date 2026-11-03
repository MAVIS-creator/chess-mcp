from __future__ import annotations

from typing import Literal

import chess

Orientation = Literal["white_bottom", "black_bottom", "unknown"]
MIN_VISUAL_CONFIDENCE = 0.90


def _validated_board(fen: str) -> chess.Board:
    try:
        board = chess.Board(fen)
    except ValueError as exc:
        raise ValueError(f"Invalid reconstructed FEN: {exc}") from exc

    if not board.is_valid():
        raise ValueError("Reconstructed FEN describes an invalid chess position.")
    return board


def validate_visual_reconstruction(
    fen: str,
    *,
    recognition_confidence: float,
    side_to_move_confirmed: bool,
    orientation: Orientation = "unknown",
    ambiguity_notes: list[str] | None = None,
) -> dict:
    """Gate engine analysis for a position reconstructed from an uploaded board image.

    The image itself is interpreted by the host vision model. This helper prevents the engine
    from treating an uncertain reconstruction as ground truth.
    """
    if not 0.0 <= recognition_confidence <= 1.0:
        raise ValueError("recognition_confidence must be between 0.0 and 1.0.")

    board = _validated_board(fen)
    notes = [note.strip() for note in (ambiguity_notes or []) if note and note.strip()]
    blockers: list[str] = []

    if recognition_confidence < MIN_VISUAL_CONFIDENCE:
        blockers.append(
            f"visual recognition confidence {recognition_confidence:.2f} is below "
            f"the {MIN_VISUAL_CONFIDENCE:.2f} safety threshold"
        )
    if not side_to_move_confirmed:
        blockers.append("side to move is not confirmed")
    if notes:
        blockers.append("one or more board squares/pieces remain ambiguous")

    return {
        "analysis_ready": not blockers,
        "normalized_fen": board.fen(),
        "turn": "white" if board.turn == chess.WHITE else "black",
        "orientation": orientation,
        "recognition_confidence": recognition_confidence,
        "side_to_move_confirmed": side_to_move_confirmed,
        "ambiguity_notes": notes,
        "blockers": blockers,
    }


def compare_visual_fens(before_fen: str, after_fen: str) -> dict:
    """Compare two reconstructed positions and infer a legal move when possible."""
    before = _validated_board(before_fen)
    after = _validated_board(after_fen)

    changed_squares: list[dict] = []
    for square in chess.SQUARES:
        before_piece = before.piece_at(square)
        after_piece = after.piece_at(square)
        before_symbol = before_piece.symbol() if before_piece else None
        after_symbol = after_piece.symbol() if after_piece else None
        if before_symbol != after_symbol:
            changed_squares.append(
                {
                    "square": chess.square_name(square),
                    "before": before_symbol,
                    "after": after_symbol,
                }
            )

    legal_matches: list[dict] = []
    for move in before.legal_moves:
        trial = before.copy(stack=False)
        san = before.san(move)
        trial.push(move)
        if trial.board_fen() == after.board_fen() and trial.turn == after.turn:
            legal_matches.append({"san": san, "uci": move.uci()})

    inferred_move = legal_matches[0] if len(legal_matches) == 1 else None
    return {
        "before_fen": before.fen(),
        "after_fen": after.fen(),
        "changed_squares": changed_squares,
        "candidate_legal_moves": legal_matches,
        "inferred_move": inferred_move,
        "unique_legal_transition": inferred_move is not None,
    }
