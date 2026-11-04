# Goldfish review 2: the README read by three strangers (a gamer with a tremor, a judge with ten minutes, a contributor)

Fresh reader, file paths only, read-only. Fifteen findings; how each was answered:

| # | Finding | Answer |
|---|---|---|
| 1 | `.\bootstrap.ps1` and `activate` are refused by the default execution policy | One-line `irm ... install.ps1 \| iex` runs the bootstrap with a process-only bypass; `.\playfellow` launcher needs no activation |
| 2 | Activation step missing after the bootstrap | Every command uses `.\playfellow`; the manual path says `python -m playfellow_coop` is the same once activated |
| 3 | Typing in the terminal takes the game out of front | Typing goes in the widget's panel (Ctrl+Alt+P, Enter), which now takes the keyboard only while open and gives the game the front back after a command (wired in the main command, tested); the terminal path says to click the game again |
| 4 | Arena command differs from JUDGES and hides the turn-limit ending | One command, `--assist 6 --typed`, and the turn-limit ending said in the README |
| 5 | No path to the Practice Arena | The exact second-window command |
| 6 | `--assist` with and without N | The default (12) is stated |
| 7 | The headline compared unlike runs | Both models, both runs, on the same 5 games; the 0 of 28 named as Muse Spark 1.3 on 14 games with no skill |
| 8 | The Layla story read as a result | Marked as an illustration, with a pointer to the measured results |
| 9 | Line 1 is jargon and defensive | Kept first: the hackathon requires the disclosure line first in the README (a repo test holds it) |
| 10 | Judges path count did not match JUDGES.md | Five ways after a one-line setup, named one by one |
| 11 | The 65 of 66 used scripted requests | Said in the results row |
| 12 | Jargon unexplained; where to get a key | "Words used here" glossary; the key link (dev.meta.ai) |
| 13 | "Open-source" next to a use-restricted licence | "Source published under OpenRAIL-S" |
| 14 | No developer setup; `-W error` in one place only | Developer setup paragraph; one test command everywhere |
| 15 | `PLAYFELLOW_ENGINE` wording, tag not named for the bootstrap | Both made the same as JUDGES.md; the tag is named in the install text |
