"""A spoken control phrase ("you take it") is consumed without the AI, so it must not leave its "key released" stopwatch behind:
otherwise the NEXT real command would be paired with the OLD release and its latency would be wrong (found in review)."""
from __future__ import annotations

from playfellow_coop import session
from playfellow_coop.handover import HandOver
from playfellow_coop.push_to_talk import VoiceLatency
from playfellow_coop.stage_timer import StageTimer
from playfellow_coop.voice import CommandQueue
from tests.test_session_and_handover import make


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_a_control_phrase_drops_its_own_release_so_the_next_command_is_timed_from_its_own():
    clock = Clock()
    latency = VoiceLatency(clock=clock)
    parts, cfg = make()
    handover = HandOver(parts.hands, parts.safety)
    commands = CommandQueue()

    clock.now = 0.0
    latency.released()  # the player let go of the talk key after "you take it" ...
    commands.put("you take it")
    clock.now = 10.0
    latency.released()  # ... and, ten seconds later, after "grab the coins"
    commands.put("grab the coins")

    clock.now = 10.5
    session.play_session(parts, cfg, "system", StageTimer(), handover, commands=commands, latency=latency, max_turns=1,
                         wait=lambda s: False)
    assert latency.samples == [0.5]  # timed from its OWN release (10.0), not from the control phrase's (0.0)


def test_discard_is_a_no_op_with_nothing_waiting():
    latency = VoiceLatency(clock=Clock())
    latency.discard()
    assert latency.samples == []
