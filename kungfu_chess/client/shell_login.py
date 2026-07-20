from __future__ import annotations
from typing import Callable

_MAX_LEN = 32


def prompt_username(read_line: Callable[[], str] = input) -> str:
    """
    Prompts until a valid username is entered.
    read_line is injected so tests never touch real stdin.
    """
    while True:
        raw = read_line().strip()
        if not raw:
            print("Username cannot be empty. Please try again.")
        elif len(raw) > _MAX_LEN:
            print(f"Username must be at most {_MAX_LEN} characters. Please try again.")
        else:
            return raw
