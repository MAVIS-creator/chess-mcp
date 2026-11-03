from __future__ import annotations

from typing import Literal

import chess

Orientation = Literal["white_bottom", "black_bottom", "unknown"]
MIN_VISUAL_CONFIDENCE = 0.90
MAX_AMBIGUITY_NOTES = 12
MAX_AMBIGUITY_NOTE_CHARS = 160


def _validated_board(fen: str) -> chess.Board:
    try:
        board = chess.Board(fen)
    except ValueError as exc:
        raise ValueError(f"Invalid reconstructed FEN: {exc}") from exc

    if not board.is_valid():
        raise ValueError("Reconstructed FEN describes an invalid chess position.")
    return board


def _validated_ambiguity_notes(ambiguity_notes: list[str] | None) -> list[str]:
    raw_notes = ambiguity_notes or []
    if len(raw_notes) > MAX_AMBIGUITY_NOTES:
        raise ValueError(
            f"ambiguity_notes may contain at most {MAX_AMBIGUITY_NOTES} entries."
        )

    notes: list[str] = []
    for note in raw_notes:
        if not isinstance(note, str):
            raise TypeError("Each ambiguity note must be a string.")
        normalized = note.strip()
        if not normalized:
            continue
        if len(normalized) > MAX_AMBIGUITY_NOTE_CHARS:
            raise ValueError(
                "Each ambiguity note must be at most "
                f"{MAX_AMBIGUITY_NOTE_CHARS} characters."
            )
        notes.append(normalized)
    return notes


def _full_fen(board: chess.Board) -> str:
    """Preserve the exact FEN en-passant square instead of normalizing it away."""
    return board.fen(en_passant="fen")


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
    notes = _validated_ambiguity_notes(ambiguity_notes)
    blockers: list[str] = []

    if recognition_confidence < MIN_VISUAL_CONFIDENCE:
        blockers.append(
            f"visual recognition confidence {recognition_confidence:.2f} is below "
            f"the {MIN_VISUAL_CONFIDENCE:.2f} safety threshold"
        )
    if not side_to_move_confirmed:
        blockers.append("side to move is not confirmed")
    if notes:
        blockers.append("one or more board squares/pieces or position-state details remain ambiguous")

    return {
        "analysis_ready": not blockers,
        "normalized_fen": _full_fen(board),
        "turn": "white" if board.turn == chess.WHITE else "black",
        "orientation": orientation,
        "recognition_confidence": recognition_confidence,
        "side_to_move_confirmed": side_to_move_confirmed,
        "ambiguity_notes": notes,
        "blockers": blockers,
    }


def _same_transition_state(trial: chess.Board, after: chess.Board) -> bool:
    """Compare state a visible move can affect while intentionally ignoring move counters."""
    return (
        trial.board_fen() == after.board_fen()
        and trial.turn == after.turn
        and trial.castling_rights == after.castling_rights
        and trial.ep_square == after.ep_square
    )


def compare_visual_fens(before_fen: str, after_fen: str) -> dict:
    """Compare two validated reconstructed positions and infer a legal move when possible."""
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
        if _same_transition_state(trial, after):
            legal_matches.append({"san": san, "uci": move.uci()})

    inferred_move = legal_matches[0] if len(legal_matches) == 1 else None
    return {
        "before_fen": _full_fen(before),
        "after_fen": _full_fen(after),
        "changed_squares": changed_squares,
        "candidate_legal_moves": legal_matches,
        "inferred_move": inferred_move,
        "unique_legal_transition": inferred_move is not None,
    }
