# Responsible use

This project is research on game-playing AI that hears a request, sees a screen and presses keys, built to play **with** people: a co-op partner, an accessibility aid, a way to learn how embodied AI works.

## Our position
- **Non-violence.** This technology must never be used for weapons, targeting, or violence against people. The binding wording is in the [LICENSE](LICENSE).
- **No surveillance.** Not for watching, tracking or profiling people without their informed consent.
- **Fair play.** Not for cheating against other players, and not for automating online or multiplayer games against their terms. We recommend offline, single-player games.
- **Adults only.** Use is for people aged 18 and over.
- **Your own key, your own account.** You use your own API key and accept the provider's terms.

## Safety built into the code
- **F12**, or moving the mouse to the top-left corner, stops everything at once and releases held keys.
- Keys go only to the one game window you chose, and only while it is in front and you have handed over the controls.
- Every action is checked against that game's controls card; anything else is dropped.
- Launchers, stores, browsers and payment windows are never controlled.
- Time, spending and call limits end a session; the daily spending cap is checked before a call is sent.
- Nothing is injected into a game, and the overlay (when used) is an ordinary window that never takes focus.
- Voice audio is not written to disk unless you turn recording on.

## Data and training
- The training data in this repository is created from our own game states and hand-written phrases, with the origin of every example recorded. **No example is taken from the output of an AI model.**
- Your own play recordings are used only with your clear, written consent.

## Reporting misuse
If you see this code used against these terms, write to the maintainer through the contact on the GitHub profile [@hesham88](https://github.com/hesham88). Security problems: see [SECURITY.md](SECURITY.md).
