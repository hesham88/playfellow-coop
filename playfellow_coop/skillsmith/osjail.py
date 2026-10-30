"""Layer 3: operating-system containment for the skill worker, so a gap in the two language layers (static gate, proxied modules) is not a full escape.

On Windows, `contain(process)` does two things to the already-started worker, before it has been sent any code (the worker may still be starting Python, but it cannot run skill code until its first message arrives, which is sent after this returns):

  * lowers the worker's integrity level to Low (S-1-16-4096). A Low process cannot write to anything a normal user file or registry key owns, which is the "arbitrary file write" case;
    lowering one's own level needs no privilege, raising it back needs SeTcb, which the worker does not have
  * puts it in a Job object that kills it when we close, allows no second process (no spawning a shell), caps its memory, and forbids touching other windows, the clipboard, global
    atoms, the desktop or system parameters

Both hold the process they are given and whatever it starts afterwards, never a process it started before: a venv's python.exe is a launcher that starts the interpreter as a
second process, so the sandbox starts only a real python.exe on Windows and refuses anything else rather than report a containment that does not hold the code.

Reads of world-readable files are not blocked by integrity levels; the scrubbed environment and the proxied modules are what keep secrets out of reach there. Elsewhere (Linux, macOS) `contain`
applies nothing and reports `"none"` (there are no address-space or process limits there); it never claims more than it did. The returned string says what was applied, so a test or a
report can state the real protection instead of assuming it.
"""
from __future__ import annotations

import sys

MEMORY_LIMIT_BYTES = 1024 * 1024 * 1024
LOW_INTEGRITY_SID = "S-1-16-4096"


def contain(process) -> str:
    """Apply what this platform offers to a started `subprocess.Popen`. Returns "low-integrity+job" on Windows when both applied, "low-integrity" or "job" when only one did, and "none"
    when neither did or on another system (never raises). Network access is not restricted by either layer."""
    if sys.platform == "win32":
        try:
            return _contain_windows(process)
        except Exception:  # noqa: BLE001 - containment is defence in depth; the other layers still hold, and the result string tells the truth
            return "none"
    return "none"


def _contain_windows(process) -> str:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    handle = wintypes.HANDLE(int(process._handle))  # type: ignore[attr-defined]  # Popen keeps the process handle here on Windows
    applied = []

    # ---- Low integrity -----------------------------------------------------------------------------------------------------------------
    TOKEN_QUERY, TOKEN_ADJUST_DEFAULT = 0x0008, 0x0080
    SE_GROUP_INTEGRITY = 0x00000020
    TokenIntegrityLevel = 25
    token = wintypes.HANDLE()
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    if advapi.OpenProcessToken(handle, TOKEN_QUERY | TOKEN_ADJUST_DEFAULT, ctypes.byref(token)):
        sid = ctypes.c_void_p()
        advapi.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
        if advapi.ConvertStringSidToSidW(LOW_INTEGRITY_SID, ctypes.byref(sid)):

            class TOKEN_MANDATORY_LABEL(ctypes.Structure):
                _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

            label = TOKEN_MANDATORY_LABEL(sid, SE_GROUP_INTEGRITY)
            advapi.SetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
            advapi.GetLengthSid.argtypes = [ctypes.c_void_p]
            advapi.GetLengthSid.restype = wintypes.DWORD
            size = ctypes.sizeof(TOKEN_MANDATORY_LABEL) + advapi.GetLengthSid(sid)  # the structure plus the length of the SID it points at
            if advapi.SetTokenInformation(token, TokenIntegrityLevel, ctypes.byref(label), size):
                applied.append("low-integrity")
            kernel.LocalFree.argtypes = [ctypes.c_void_p]
            kernel.LocalFree(sid)
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle(token)

    # ---- Job object ----------------------------------------------------------------------------------------------------------------------
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    job = kernel.CreateJobObjectW(None, None)
    if job:
        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")]

        class EXTENDED(ctypes.Structure):
            _fields_ = [("Basic", BASIC), ("Io", IO), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        LIMIT_ACTIVE_PROCESS, LIMIT_PROCESS_MEMORY, LIMIT_KILL_ON_CLOSE = 0x8, 0x100, 0x2000
        info = EXTENDED()
        info.Basic.LimitFlags = LIMIT_ACTIVE_PROCESS | LIMIT_PROCESS_MEMORY | LIMIT_KILL_ON_CLOSE
        info.Basic.ActiveProcessLimit = 1
        info.ProcessMemoryLimit = MEMORY_LIMIT_BYTES
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        ok = kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))  # JobObjectExtendedLimitInformation

        class UI(ctypes.Structure):
            _fields_ = [("UIRestrictionsClass", wintypes.DWORD)]

        # desktop, display settings, exit windows, global atoms, handles of other processes' windows, read and write clipboard, system parameters
        ui = UI(0x40 | 0x10 | 0x80 | 0x20 | 0x01 | 0x02 | 0x04 | 0x08)
        ok = ok and kernel.SetInformationJobObject(job, 4, ctypes.byref(ui), ctypes.sizeof(ui))  # JobObjectBasicUIRestrictions
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        if ok and kernel.AssignProcessToJobObject(job, handle):
            applied.append("job")
            process._pf_job = job  # keep the handle open for the life of the process: closing it kills the worker, which is what we want at close()
        else:
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle(job)  # nothing was assigned, so the handle is not needed
    return "+".join(applied) or "none"
