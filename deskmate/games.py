"""Mini-games with her: the rules, in pure Python (the windows and chips are in fun.py).

* Rock, paper, scissors: best of three.
* Tic-tac-toe: she plays well, but not perfectly (she's playing *with* you, after all).
* Hide and seek: the rules are simple enough to live in fun.py.
"""

from __future__ import annotations

import random
from functools import lru_cache

# ------------------------------------------------------------ rock paper scissors
MOVES = ("rock", "paper", "scissors")
EMOJI = {"rock": "✊", "paper": "✋", "scissors": "✌️"}
BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}


def judge(you: str, her: str) -> str:
    """"win", "lose" or "draw" (for you)."""
    if you == her:
        return "draw"
    return "win" if BEATS[you] == her else "lose"


class RockPaperScissors:
    """First to two wins (draws don't count)."""

    def __init__(self, rng: random.Random | None = None, to_win: int = 2):
        self.rng = rng or random.Random()
        self.to_win = to_win
        self.you = self.her = 0
        self.rounds: list[tuple[str, str, str]] = []

    def play(self, you: str) -> tuple[str, str]:
        """You show ``you``; returns (her move, "win"/"lose"/"draw")."""
        her = self.rng.choice(MOVES)
        result = judge(you, her)
        if result == "win":
            self.you += 1
        elif result == "lose":
            self.her += 1
        self.rounds.append((you, her, result))
        return her, result

    @property
    def over(self) -> bool:
        return max(self.you, self.her) >= self.to_win

    @property
    def winner(self) -> str | None:
        """"you", "her" or None (not over yet)."""
        if not self.over:
            return None
        return "you" if self.you > self.her else "her"

    def score(self) -> str:
        return f"{self.you}–{self.her}"


# --------------------------------------------------------------------- tic-tac-toe
LINES = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]


def winner(board: list[str]) -> str | None:
    """"X", "O", "draw" or None (still playing). The board is 9 cells: "X", "O" or ""."""
    for a, b, c in LINES:
        if board[a] and board[a] == board[b] == board[c]:
            return board[a]
    return "draw" if all(board) else None


def winning_line(board: list[str]) -> tuple[int, int, int] | None:
    for line in LINES:
        a, b, c = line
        if board[a] and board[a] == board[b] == board[c]:
            return line
    return None


@lru_cache(maxsize=None)
def _minimax(board: tuple[str, ...], me: str, turn: str) -> int:
    """How good ``board`` is for ``me`` with ``turn`` to play: sooner wins score higher, later losses less badly."""
    result = winner(list(board))
    empty = board.count("")
    if result == me:
        return 1 + empty
    if result == "draw":
        return 0
    if result is not None:
        return -1 - empty
    other = "O" if turn == "X" else "X"
    scores = [_minimax(board[:i] + (turn,) + board[i + 1:], me, other) for i in range(9) if not board[i]]
    return max(scores) if turn == me else min(scores)


def best_move(board: list[str], me: str = "O") -> int:
    """The best cell for ``me`` (a perfect player)."""
    other = "X" if me == "O" else "O"
    cells = tuple(board)
    best, best_score = -1, -100
    for i in range(9):
        if not cells[i]:
            score = _minimax(cells[:i] + (me,) + cells[i + 1:], me, other)
            if score > best_score or (score == best_score and i == 4):  # (likes the middle)
                best, best_score = i, score
    return best


class TicTacToe:
    """You are X and go first; she is O. ``mistakes``: how often she plays a random move instead."""

    def __init__(self, rng: random.Random | None = None, mistakes: float = 0.25):
        self.rng = rng or random.Random()
        self.mistakes = mistakes
        self.board = [""] * 9

    @property
    def result(self) -> str | None:
        return winner(self.board)

    def play(self, cell: int) -> int | None:
        """You play ``cell``; then she answers (returns her cell, or None if the game ended / the cell was taken)."""
        if self.result is not None or not 0 <= cell < 9 or self.board[cell]:
            return None
        self.board[cell] = "X"
        if self.result is not None:
            return None
        free = [i for i in range(9) if not self.board[i]]
        if self.rng.random() < self.mistakes:
            move = self.rng.choice(free)
        else:
            move = best_move(self.board, "O")
        self.board[move] = "O"
        return move
