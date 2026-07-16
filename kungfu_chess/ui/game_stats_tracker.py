"""
Listens to RealTimeEvents from GameEngine.wait() and accumulates move history and scores.
Pure stats layer — no game logic, no rendering.
"""
from kungfu_chess.model.piece import PieceColor, PieceKind
from kungfu_chess.model.game_state import MoveRecord
from kungfu_chess.realtime.motion import ArrivalEvent, EliminationEvent
from kungfu_chess.ui.assets.asset_paths import COL_LETTERS


class GameStatsTracker:

    def __init__(self, board_height: int, piece_scores: dict):
        """piece_scores: dict mapping PieceKind.value (str) -> int, e.g. {"P": 1, "Q": 9, ...}"""
        self._board_height = board_height
        self._piece_scores = {PieceKind(k): v for k, v in piece_scores.items()}
        self._scores: dict[PieceColor, int] = {PieceColor.WHITE: 0, PieceColor.BLACK: 0}
        self._move_history: list[MoveRecord] = []
        self._elapsed_ms: int = 0

    def process(self, events: list, delta_ms: int) -> None:
        self._elapsed_ms += delta_ms
        for event in events:
            if isinstance(event, ArrivalEvent):
                self._record_move(event)
                if event.captured_piece is not None:
                    self._add_score(event.arriving_piece.color, event.captured_piece.kind)
            elif isinstance(event, EliminationEvent):
                attacker_color = PieceColor.WHITE if event.piece.color == PieceColor.BLACK else PieceColor.BLACK
                self._add_score(attacker_color, event.piece.kind)

    def _add_score(self, attacker_color: PieceColor, captured_kind: PieceKind) -> None:
        self._scores[attacker_color] += self._piece_scores.get(captured_kind, 0)

    def _record_move(self, event: ArrivalEvent) -> None:
        kind = event.pre_promotion_kind if event.pre_promotion_kind is not None else event.arriving_piece.kind
        col = COL_LETTERS[event.destination.col]
        row = self._board_height - event.destination.row
        kind_letter = "" if kind == PieceKind.PAWN else kind.value
        self._move_history.append(MoveRecord(
            elapsed_ms=self._elapsed_ms,
            notation=f"{kind_letter}{col}{row}",
            color=event.arriving_piece.color,
        ))

    @property
    def scores(self) -> dict[PieceColor, int]:
        return dict(self._scores)

    @property
    def move_history(self) -> list[MoveRecord]:
        return list(self._move_history)
