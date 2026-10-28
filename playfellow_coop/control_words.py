"""The few spoken (or typed) words that steer the HAND-OVER itself, matched exactly, with no AI: "stop", "you take it", "I've got it".

They are recognised before a command goes to the planner, so "stop" works at once even if the AI is slow or down (F12 still works too).
Anything else is an ordinary command. The match is on the whole phrase after removing punctuation and Arabic marks, so a longer
sentence that merely contains the word ("don't stop at the door") is NOT a control word."""
from __future__ import annotations

import re
import unicodedata

STOP, BUDDY_TAKES, PLAYER_TAKES, APPROVE, DECLINE = "stop", "buddy_takes", "player_takes", "approve", "decline"

PHRASES = {
    STOP: {"stop", "stop now", "stop it", "halt", "وقف", "وقّف", "قف", "وقف دلوقتي", "اوقف", "أوقف"},
    BUDDY_TAKES: {"you take it", "you take over", "you go", "your turn", "خذها", "انت خدها", "إنت خدها", "دورك", "كمل انت", "كمّل انت"},
    PLAYER_TAKES: {"i've got it", "i have got it", "i got it", "i'll take it", "my turn", "give it back", "أنا هكمل", "انا هكمل",
                   "أنا سأكمل", "دوري", "رجّعها", "رجعها"},
    # the player's answer to a safety check of the computer-use brain; whole phrases only, so a sentence that merely contains them is an ordinary command
    APPROVE: {"approve", "approve it", "approve the action", "yes do it", "yes go ahead", "نفذ", "نفّذ", "موافق"},
    DECLINE: {"decline", "decline it", "don't do it", "do not do it", "no don't", "لا تنفذ", "لا تنفّذ", "ارفض", "مش موافق"},
}
_MARKS = dict.fromkeys(map(ord, "ًٌٍَُِّْـ"))  # Arabic short vowels, shadda, tatweel


def _normal(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").translate(_MARKS).lower()
    text = re.sub(r"[^\w\s']", " ", text.replace("’", "'"))  # punctuation goes; apostrophes stay ("i've")
    return " ".join(text.split())


_TABLE = {_normal(phrase): action for action, phrases in PHRASES.items() for phrase in phrases}


def control_action(text: str) -> str | None:
    """STOP, BUDDY_TAKES, PLAYER_TAKES, APPROVE, DECLINE, or None for an ordinary command."""
    return _TABLE.get(_normal(text))


def split(commands: list[str]) -> tuple[list[str], list[str]]:
    """(ordinary commands for the planner, control actions in the order they were said)."""
    ordinary, actions = [], []
    for command in commands:
        action = control_action(command)
        (actions if action else ordinary).append(action or command)
    return ordinary, actions
