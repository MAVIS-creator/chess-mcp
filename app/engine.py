from __future__ import annotations

import os
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

import chess
import chess.engine

MAX_TIME_MS = int(os.getenv("MAX_ANALYSIS_MS", "15000"))
MAX_MULTIPV = int(os.getenv("MAX_MULTIPV", "8"))
MAX_DEPTH = int(os.getenv("MAX_DEPTH", "40"))
MAX_NODES = int(os.getenv("MAX_NODES", "50000000"))

AnalysisProfile = Literal["quick", "normal", "deep"]

ANALYSIS_PROFILES: dict[AnalysisProfile, dict[str, int]] = {
    "quick": {
        "initial_time_ms": 500,
        "confirm_time_ms": 1500,
        "multipv": 2,
    },
    "normal": {
        "initial_time_ms": 1200,
        "confirm_time_ms": 3500,
        "multipv": 4,
    },
    "deep": {
        "initial_time_ms": 3000,
        "confirm_time_ms": 8000,
        "multipv": 5,
    },
}


@dataclass(frozen=True)
class EngineSettings:
    path: str = os.getenv("STOCKFISH_PATH", "/usr/local/bin/stockfish")
    threads: int = int(os.getenv("STOCKFISH_THREADS", "2"))
    hash_mb: int = int(os.getenv("STOCKFISH_HASH_MB", "512"))


class StockfishService:
    """Single Stockfish process guarded by a lock.

    Cloud Run is deployed with concurrency=1 by default in this project, but the
    lock still protects local/dev usage and future configuration changes.
    """

    def __init__(self, settings: EngineSettings | None = None) -> None:
        self.settings = settings or EngineSettings()
        self._engine: chess.engine.SimpleEngine | None = None
        self._lock = threading.RLock()

    def _ensure_engine(self) -> chess.engine.SimpleEngine:
        if self._engine is None:
            engine = chess.engine.SimpleEngine.popen_uci(self.settings.path)
            config: dict[str, Any] = {}
            if "Threads" in engine.options:
                config["Threads"] = max(1, self.settings.threads)
            if "Hash" in engine.options:
                hash_opt = engine.options["Hash"]
                max_hash = getattr(hash_opt, "max", None)
                value = max(16, self.settings.hash_mb)
                if isinstance(max_hash, int):
                    value = min(value, max_hash)
                config["Hash"] = value
            if config:
                engine.configure(config)
            self._engine = engine
        return self._engine

    def close(self) -> None:
        with self._lock:
            if self._engine is not None:
                try:
                    self._engine.quit()
                except (chess.engine.EngineError, OSError):
                    pass
                finally:
                    self._engine = None

    @staticmethod
    def board_from_fen(fen: str) -> chess.Board:
        try:
            board = chess.Board(fen)
        except ValueError as exc:
            raise ValueError(f"Invalid FEN: {exc}") from exc
        if not board.is_valid():
            raise ValueError("The FEN describes an invalid chess position.")
        return board

    @staticmethod
    def parse_move(board: chess.Board, move_text: str) -> chess.Move:
        text = move_text.strip()
        try:
            move = chess.Move.from_uci(text.lower())
            if move in board.legal_moves:
                return move
        except ValueError:
            pass
        try:
            return board.parse_san(text)
        except ValueError as exc:
            raise ValueError(f"Illegal or unrecognized move '{move_text}'. Use SAN or UCI.") from exc

    @staticmethod
    def profile_settings(profile: AnalysisProfile) -> dict[str, int]:
        if profile not in ANALYSIS_PROFILES:
            raise ValueError(f"Unknown analysis profile: {profile}")
        settings = dict(ANALYSIS_PROFILES[profile])
        settings["initial_time_ms"] = min(settings["initial_time_ms"], MAX_TIME_MS)
        settings["confirm_time_ms"] = min(settings["confirm_time_ms"], MAX_TIME_MS)
        settings["multipv"] = min(settings["multipv"], MAX_MULTIPV)
        return settings

    @staticmethod
    def _normalize_limits(
        *,
        time_ms: int | None = None,
        depth: int | None = None,
        nodes: int | None = None,
    ) -> chess.engine.Limit:
        safe_time = None if time_ms is None else max(50, min(int(time_ms), MAX_TIME_MS)) / 1000.0
        safe_depth = None if depth is None else max(1, min(int(depth), MAX_DEPTH))
        safe_nodes = None if nodes is None else max(1, min(int(nodes), MAX_NODES))
        if safe_time is None and safe_depth is None and safe_nodes is None:
            safe_time = 1.5
        return chess.engine.Limit(time=safe_time, depth=safe_depth, nodes=safe_nodes)

    @staticmethod
    def _score_payload(score: chess.engine.PovScore, board: chess.Board) -> dict[str, Any]:
        pov = score.pov(board.turn)
        mate = pov.mate()
        cp = pov.score()
        numeric = pov.score(mate_score=100000)
        payload: dict[str, Any] = {
            "perspective": "side_to_move",
            "centipawns": cp,
            "pawns": None if cp is None else round(cp / 100.0, 2),
            "mate_in": mate,
            "numeric_for_sorting": numeric,
            "text": str(pov),
        }
        wdl = pov.wdl(model="sf", ply=max(1, board.ply()))
        payload["wdl_per_1000"] = {
            "wins": int(wdl.wins),
            "draws": int(wdl.draws),
            "losses": int(wdl.losses),
        }
        return payload

    @staticmethod
    def _pv_payload(board: chess.Board, pv: Iterable[chess.Move]) -> dict[str, list[str]]:
        temp = board.copy(stack=False)
        san: list[str] = []
        uci: list[str] = []
        for move in pv:
            if move not in temp.legal_moves:
                break
            uci.append(move.uci())
            san.append(temp.san(move))
            temp.push(move)
        return {"san": san, "uci": uci}

    def _info_payload(self, board: chess.Board, info: dict[str, Any]) -> dict[str, Any]:
        score = info.get("score")
        pv = info.get("pv", [])
        first_move = pv[0] if pv else None
        first_san = None
        if first_move is not None:
            first_san = board.san(first_move)
        return {
            "move": first_san,
            "move_uci": None if first_move is None else first_move.uci(),
            "score": None if score is None else self._score_payload(score, board),
            "depth": info.get("depth"),
            "seldepth": info.get("seldepth"),
            "nodes": info.get("nodes"),
            "nps": info.get("nps"),
            "hashfull": info.get("hashfull"),
            "time_seconds": info.get("time"),
            "pv": self._pv_payload(board, pv),
        }

    def _run_analysis(
        self,
        board: chess.Board,
        limit: chess.engine.Limit,
        *,
        multipv: int,
        root_moves: list[chess.Move] | None,
    ) -> list[dict[str, Any]]:
        """Run one engine search and recover once if the Stockfish process died."""
        for attempt in range(2):
            try:
                engine = self._ensure_engine()
                result = engine.analyse(
                    board,
                    limit,
                    multipv=multipv,
                    root_moves=root_moves,
                )
                return result if isinstance(result, list) else [result]
            except (chess.engine.EngineError, OSError):
                self.close()
                if attempt == 1:
                    raise
        raise RuntimeError("Stockfish analysis failed unexpectedly.")

    def analyze(
        self,
        fen: str,
        *,
        time_ms: int = 1500,
        multipv: int = 3,
        depth: int | None = None,
        nodes: int | None = None,
        root_moves: list[str] | None = None,
    ) -> dict[str, Any]:
        board = self.board_from_fen(fen)
        safe_multipv = max(1, min(int(multipv), MAX_MULTIPV))
        limit = self._normalize_limits(time_ms=time_ms, depth=depth, nodes=nodes)

        parsed_root_moves: list[chess.Move] | None = None
        if root_moves:
            parsed_root_moves = [self.parse_move(board, move) for move in root_moves]
            safe_multipv = min(safe_multipv, len(parsed_root_moves))

        with self._lock:
            infos = self._run_analysis(
                board,
                limit,
                multipv=safe_multipv,
                root_moves=parsed_root_moves,
            )

        lines = [self._info_payload(board, info) for info in infos]
        return {
            "fen": board.fen(),
            "turn": "white" if board.turn == chess.WHITE else "black",
            "in_check": board.is_check(),
            "fullmove_number": board.fullmove_number,
            "lines": lines,
            "best_move": lines[0]["move"] if lines else None,
            "best_move_uci": lines[0]["move_uci"] if lines else None,
        }

    def compare_moves(self, fen: str, moves: list[str], *, time_ms: int = 2000) -> dict[str, Any]:
        board = self.board_from_fen(fen)
        if not moves:
            raise ValueError("Provide at least one candidate move.")
        if len(moves) > MAX_MULTIPV:
            raise ValueError(f"At most {MAX_MULTIPV} candidate moves can be compared at once.")

        requested_by_uci: dict[str, str] = {}
        root_moves: list[str] = []
        for move_text in moves:
            move = self.parse_move(board, move_text)
            uci = move.uci()
            if uci in requested_by_uci:
                continue
            requested_by_uci[uci] = board.san(move)
            root_moves.append(uci)

        analysis = self.analyze(
            fen,
            time_ms=time_ms,
            multipv=len(root_moves),
            root_moves=root_moves,
        )

        ranking = []
        for line in analysis["lines"]:
            move_uci = line.get("move_uci")
            ranking.append(
                {
                    "requested_move": requested_by_uci.get(str(move_uci)),
                    "requested_move_uci": move_uci,
                    **line,
                }
            )

        return {
            "fen": board.fen(),
            "turn": "white" if board.turn == chess.WHITE else "black",
            "ranking": ranking,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            engine = self._ensure_engine()
            return {
                "ok": True,
                "engine_id": dict(engine.id),
                "path": self.settings.path,
                "threads": self.settings.threads,
                "hash_mb": self.settings.hash_mb,
                "analysis_profiles": ANALYSIS_PROFILES,
                "limits": {
                    "max_analysis_ms": MAX_TIME_MS,
                    "max_multipv": MAX_MULTIPV,
                    "max_depth": MAX_DEPTH,
                    "max_nodes": MAX_NODES,
                },
            }


service = StockfishService()
