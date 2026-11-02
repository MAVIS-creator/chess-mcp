from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

import chess

DEFAULT_NETWORK_TIMEOUT_MS = int(os.getenv("CONTEXT_NETWORK_TIMEOUT_MS", "1200"))
TABLEBASE_URL = os.getenv("TABLEBASE_URL", "https://tablebase.lichess.org/standard")
OPENING_EXPLORER_URL = os.getenv(
    "OPENING_EXPLORER_URL", "https://explorer.lichess.org/masters"
)
LICHESS_TOKEN = os.getenv("LICHESS_TOKEN", "").strip()
HISTORY_BACKEND = os.getenv("HISTORY_BACKEND", "none").strip().lower()
HISTORY_COLLECTION = os.getenv("HISTORY_COLLECTION", "chess_player_history")
HISTORY_MAX_EVENTS = max(10, min(int(os.getenv("HISTORY_MAX_EVENTS", "80")), 250))
HISTORY_WRITES_ENABLED = os.getenv("HISTORY_WRITES_ENABLED", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def position_key(fen: str) -> str:
    """Return the repetition-relevant part of a normalized FEN."""
    board = chess.Board(fen)
    return " ".join(board.fen().split()[:4])


def _request_json(
    url: str,
    *,
    params: dict[str, str],
    timeout_ms: int,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{url}?{query}",
        headers={"User-Agent": "chatgpt-stockfish-mcp/0.3", **(headers or {})},
    )
    timeout_seconds = max(0.1, min(timeout_ms, 5000) / 1000.0)
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        payload = response.read(1_000_000)
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise ValueError("Expected a JSON object from chess context provider.")
    return parsed


class TTLCache:
    def __init__(self, ttl_seconds: int = 300, max_entries: int = 512) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._values: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = threading.RLock()

    def get(self, key: str) -> dict[str, Any] | None:
        now = time.monotonic()
        with self._lock:
            item = self._values.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at <= now:
                self._values.pop(key, None)
                return None
            return value

    def put(self, key: str, value: dict[str, Any]) -> None:
        with self._lock:
            if len(self._values) >= self.max_entries:
                oldest_key = next(iter(self._values), None)
                if oldest_key is not None:
                    self._values.pop(oldest_key, None)
            self._values[key] = (time.monotonic() + self.ttl_seconds, value)


_LOCAL_OPENINGS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("King's Pawn Game", ("e4",)),
    ("Queen's Pawn Game", ("d4",)),
    ("English Opening", ("c4",)),
    ("Reti Opening", ("Nf3",)),
    ("Sicilian Defense", ("e4", "c5")),
    ("French Defense", ("e4", "e6")),
    ("Caro-Kann Defense", ("e4", "c6")),
    ("Scandinavian Defense", ("e4", "d5")),
    ("Alekhine Defense", ("e4", "Nf6")),
    ("Pirc Defense", ("e4", "d6")),
    ("Modern Defense", ("e4", "g6")),
    ("Petrov Defense", ("e4", "e5", "Nf3", "Nf6")),
    ("Vienna Game", ("e4", "e5", "Nc3")),
    ("Scotch Game", ("e4", "e5", "Nf3", "Nc6", "d4")),
    ("Italian Game", ("e4", "e5", "Nf3", "Nc6", "Bc4")),
    ("Ruy Lopez", ("e4", "e5", "Nf3", "Nc6", "Bb5")),
    ("Queen's Gambit", ("d4", "d5", "c4")),
    ("Slav Defense", ("d4", "d5", "c4", "c6")),
    ("London System", ("d4", "d5", "Nf3", "Nf6", "Bf4")),
    ("Dutch Defense", ("d4", "f5")),
    ("King's Indian Defense", ("d4", "Nf6", "c4", "g6", "Nc3", "Bg7")),
    ("Nimzo-Indian Defense", ("d4", "Nf6", "c4", "e6", "Nc3", "Bb4")),
    ("Queen's Indian Defense", ("d4", "Nf6", "c4", "e6", "Nf3", "b6")),
    ("Grunfeld Defense", ("d4", "Nf6", "c4", "g6", "Nc3", "d5")),
    ("Benoni Defense", ("d4", "Nf6", "c4", "c5", "d5")),
    ("Catalan Opening", ("d4", "Nf6", "c4", "e6", "g3", "d5", "Bg2")),
)


def _build_local_opening_index() -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for name, moves in _LOCAL_OPENINGS:
        board = chess.Board()
        uci_moves: list[str] = []
        try:
            for san in moves:
                move = board.parse_san(san)
                uci_moves.append(move.uci())
                board.push(move)
        except ValueError:
            continue
        index[position_key(board.fen())] = {
            "name": name,
            "source": "local",
            "moves_uci": uci_moves,
            "ply": board.ply(),
        }
    return index


_LOCAL_OPENING_INDEX = _build_local_opening_index()


@dataclass(frozen=True)
class ContextSettings:
    network_timeout_ms: int = DEFAULT_NETWORK_TIMEOUT_MS
    tablebase_url: str = TABLEBASE_URL
    opening_explorer_url: str = OPENING_EXPLORER_URL


class PlayerHistoryStore:
    """Optional Firestore-backed personal chess history."""

    def __init__(self) -> None:
        self.enabled = HISTORY_BACKEND == "firestore"
        self.writes_enabled = self.enabled and HISTORY_WRITES_ENABLED
        self._client: Any | None = None
        self._lock = threading.RLock()

    def _get_client(self) -> Any:
        if not self.enabled:
            raise RuntimeError("Player history is disabled.")
        with self._lock:
            if self._client is None:
                from google.cloud import firestore

                project = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or None
                self._client = firestore.Client(project=project)
            return self._client

    @staticmethod
    def _safe_player_id(player_id: str) -> str:
        value = player_id.strip()
        if not value or len(value) > 120:
            raise ValueError("player_id must contain 1-120 characters.")
        return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in value)

    def get(self, player_id: str, fen: str) -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "backend": HISTORY_BACKEND, "events": []}
        safe_id = self._safe_player_id(player_id)
        key = position_key(fen)
        try:
            snapshot = self._get_client().collection(HISTORY_COLLECTION).document(safe_id).get()
            data = snapshot.to_dict() if snapshot.exists else {}
            raw_events = data.get("events", []) if isinstance(data, dict) else []
            events = [event for event in raw_events if isinstance(event, dict)]
            exact = [event for event in events if event.get("position_key") == key][-8:]
            recent = events[-8:]
            losses = [
                int(event["loss_cp"])
                for event in exact
                if isinstance(event.get("loss_cp"), (int, float))
            ]
            return {
                "enabled": True,
                "writes_enabled": self.writes_enabled,
                "backend": "firestore",
                "player_id": safe_id,
                "exact_position_events": exact,
                "recent_events": recent,
                "exact_position_count": len(exact),
                "average_exact_loss_cp": (
                    round(sum(losses) / len(losses), 1) if losses else None
                ),
            }
        except Exception as exc:
            return {
                "enabled": True,
                "writes_enabled": self.writes_enabled,
                "backend": "firestore",
                "available": False,
                "error": type(exc).__name__,
                "events": [],
            }

    def record(
        self,
        player_id: str,
        fen: str,
        *,
        played_move: str | None = None,
        best_move: str | None = None,
        loss_cp: int | None = None,
        outcome: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {
                "stored": False,
                "reason": "HISTORY_BACKEND is not set to firestore",
            }
        if not self.writes_enabled:
            return {
                "stored": False,
                "reason": (
                    "History writes are disabled on this public deployment. Enable them only "
                    "after compatible MCP authentication/rate limiting is configured."
                ),
            }
        safe_id = self._safe_player_id(player_id)
        event = {
            "position_key": position_key(fen),
            "fen": chess.Board(fen).fen(),
            "played_move": played_move,
            "best_move": best_move,
            "loss_cp": None if loss_cp is None else int(loss_cp),
            "outcome": outcome,
            "note": None if note is None else note[:500],
            "recorded_at_epoch": int(time.time()),
        }
        try:
            document = self._get_client().collection(HISTORY_COLLECTION).document(safe_id)
            snapshot = document.get()
            data = snapshot.to_dict() if snapshot.exists else {}
            existing = data.get("events", []) if isinstance(data, dict) else []
            events = [item for item in existing if isinstance(item, dict)]
            events.append(event)
            events = events[-HISTORY_MAX_EVENTS:]
            document.set({"events": events, "updated_at_epoch": int(time.time())}, merge=True)
            return {"stored": True, "player_id": safe_id, "event": event}
        except Exception as exc:
            return {"stored": False, "error": type(exc).__name__}


class ChessContextService:
    def __init__(self, settings: ContextSettings | None = None) -> None:
        self.settings = settings or ContextSettings()
        self.opening_cache = TTLCache(ttl_seconds=600)
        self.tablebase_cache = TTLCache(ttl_seconds=3600)
        self.history = PlayerHistoryStore()

    def local_opening(self, fen: str) -> dict[str, Any]:
        key = position_key(fen)
        hit = _LOCAL_OPENING_INDEX.get(key)
        if hit is None:
            return {"available": False, "source": "local"}
        return {"available": True, **hit}

    def opening_context(self, fen: str, timeout_ms: int | None = None) -> dict[str, Any]:
        board = chess.Board(fen)
        normalized = board.fen()
        key = position_key(normalized)
        cached = self.opening_cache.get(key)
        if cached is not None:
            return {**cached, "cached": True}

        local = self.local_opening(normalized)
        if not LICHESS_TOKEN:
            result = {
                **local,
                "remote_available": False,
                "remote_reason": "LICHESS_TOKEN not configured",
            }
            self.opening_cache.put(key, result)
            return result

        headers = {"Authorization": f"Bearer {LICHESS_TOKEN}"}
        try:
            payload = _request_json(
                self.settings.opening_explorer_url,
                params={"fen": normalized, "moves": "8", "topGames": "3", "recentGames": "0"},
                timeout_ms=timeout_ms or self.settings.network_timeout_ms,
                headers=headers,
            )
            moves = []
            for move in payload.get("moves", [])[:8]:
                if not isinstance(move, dict):
                    continue
                moves.append(
                    {
                        "san": move.get("san"),
                        "uci": move.get("uci"),
                        "white": move.get("white", 0),
                        "draws": move.get("draws", 0),
                        "black": move.get("black", 0),
                        "average_rating": move.get("averageRating"),
                    }
                )
            result = {
                "available": True,
                "source": "lichess-masters",
                "opening": payload.get("opening") or (local if local.get("available") else None),
                "white": payload.get("white", 0),
                "draws": payload.get("draws", 0),
                "black": payload.get("black", 0),
                "moves": moves,
                "top_games": payload.get("topGames", [])[:3],
                "local_fallback": local,
                "remote_available": True,
            }
        except Exception as exc:
            result = {
                **local,
                "remote_available": False,
                "remote_error": type(exc).__name__,
            }
        self.opening_cache.put(key, result)
        return result

    def tablebase_context(self, fen: str, timeout_ms: int | None = None) -> dict[str, Any]:
        board = chess.Board(fen)
        piece_count = len(board.piece_map())
        if piece_count > 7:
            return {
                "applicable": False,
                "available": False,
                "piece_count": piece_count,
                "reason": "standard Syzygy is queried only for positions with 7 or fewer pieces",
            }

        normalized = board.fen()
        key = position_key(normalized)
        cached = self.tablebase_cache.get(key)
        if cached is not None:
            return {**cached, "cached": True}

        try:
            payload = _request_json(
                self.settings.tablebase_url,
                params={"fen": normalized},
                timeout_ms=timeout_ms or self.settings.network_timeout_ms,
            )
            moves = []
            for move in payload.get("moves", [])[:8]:
                if isinstance(move, dict):
                    moves.append(
                        {
                            "san": move.get("san"),
                            "uci": move.get("uci"),
                            "category": move.get("category"),
                            "dtz": move.get("dtz"),
                            "dtm": move.get("dtm"),
                            "zeroing": move.get("zeroing"),
                            "checkmate": move.get("checkmate"),
                        }
                    )
            category = payload.get("category")
            result = {
                "applicable": True,
                "available": category is not None,
                "exact": category is not None and category != "unknown",
                "piece_count": piece_count,
                "category": category,
                "dtz": payload.get("dtz"),
                "precise_dtz": payload.get("precise_dtz"),
                "dtm": payload.get("dtm"),
                "checkmate": payload.get("checkmate", False),
                "stalemate": payload.get("stalemate", False),
                "insufficient_material": payload.get("insufficient_material", False),
                "moves": moves,
                "source": "lichess-syzygy",
            }
        except Exception as exc:
            result = {
                "applicable": True,
                "available": False,
                "exact": False,
                "piece_count": piece_count,
                "error": type(exc).__name__,
            }
        self.tablebase_cache.put(key, result)
        return result

    def history_context(self, player_id: str | None, fen: str) -> dict[str, Any]:
        if not player_id:
            return {
                "enabled": self.history.enabled,
                "writes_enabled": self.history.writes_enabled,
                "provided": False,
                "events": [],
            }
        return self.history.get(player_id, fen)


context_service = ChessContextService()
