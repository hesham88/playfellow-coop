# Security

Please **don't** open a public issue for a security problem. Report it privately with GitHub's **"Report a vulnerability"** button (the Security tab of this repository), with steps to reproduce.

This is a single-maintainer project. I will answer as soon as I can and credit you in the fix if you wish. Only the current `main` branch is supported.

**Most important to us:**
- any way input could reach a window other than the game chosen by the player, or bypass the F12 stop, the controls-card allow-list or the blocked-window list;
- any way the hand-over could keep pressing keys after the player took the controls;
- any leak of an API key, a spoken or typed command, personal data or screen content;
- any way a request could be sent to a host other than the pinned Meta API host, through a proxy, a redirect or an environment variable;
- the spending caps: anything that lets a call go out after the daily cap is reached.

**API keys never belong in this repository.** Keys are read from the `MODEL_API_KEY` environment variable or the operating system's credential store at run time. If you ever find a key, a token or a personal path in this repository, report it privately; do not repeat it in an issue.

**Scope.** This repository holds the event work (the Muse brain, SAM marks, voice, the hand-over, the benchmarks, the web demo and the training pipeline). The engine it plugs into has its own policy at `hesham88/playfellow`.
