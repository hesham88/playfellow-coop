"""Power guard: the buddy pauses before the laptop browns out.

Found on 3 November: two instant power-offs (Kernel-Power 41, bugcheck 0, no button press) during play. The battery was worn
to 25% of its design capacity and sat at 0%, so it could not cover load spikes the charger alone cannot feed. While the
buddy plays, a background thread reads the battery every few seconds; when the machine is plugged in yet drawing from the
battery (past what the charger gives), or the battery is nearly empty and discharging, `danger()` turns true and the live
loop lets go of every key and waits, saying why in the widget.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable


@dataclass
class Reading:
    on_ac: bool
    discharging: bool
    remaining_mwh: int | None
    rate_mw: int | None


def judge(reading: Reading | None, low_mwh: int = 1500) -> str | None:
    """Why it is unsafe to keep the load up now, or None."""
    if reading is None:
        return None
    if reading.on_ac and reading.discharging:
        return "plugged in but drawing from the battery: the load is past what the charger gives"
    if not reading.on_ac and reading.discharging and reading.remaining_mwh is not None and reading.remaining_mwh < low_mwh:
        return "on battery and nearly empty"
    return None


def read_battery() -> Reading | None:  # pragma: no cover - needs the real machine
    """One reading from WMI root/wmi BatteryStatus (None when the machine has no battery or WMI will not answer)."""
    try:
        import subprocess

        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "$b=Get-CimInstance -Namespace root/wmi -ClassName BatteryStatus | Select-Object -First 1; "
                              "\"$($b.PowerOnline),$($b.Discharging),$($b.RemainingCapacity),$($b.DischargeRate)\""],
                             capture_output=True, text=True, timeout=10, creationflags=0x08000000).stdout.strip()
        on_ac, dis, rem, rate = out.split(",")
        return Reading(on_ac == "True", dis == "True", int(rem) if rem else None, int(rate) if rate else None)
    except Exception:
        return None


class PowerGuard:
    def __init__(self, read: Callable[[], Reading | None] = read_battery, every: float = 15.0):
        self.read, self.every = read, every
        self.last: Reading | None = None
        self.reason: str | None = None
        self.trips = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="power-guard", daemon=True)

    def start(self) -> "PowerGuard":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.last = self.read()
            reason = judge(self.last)
            if reason and not self.reason:
                self.trips += 1
            self.reason = reason
            self._stop.wait(self.every)

    def danger(self) -> str | None:
        return self.reason
