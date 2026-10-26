# Contributing

Thank you for wanting to help. This project is open to your ideas, bug reports and pull requests, and **every contribution is reviewed in depth by the maintainer, [@hesham88](https://github.com/hesham88), before anything is merged.** Nobody else has write access.

## When contributions can be merged

This repository was built **during the Meta Global AI Developer Hackathon (26 Oct to 4 Nov 2026)**, and the event requires that everything submitted was made by approved participants during the event. So:

- **Until the judging ends (9 Nov 2026), no outside change is merged into `main`.** You are welcome to open issues and pull requests, and to discuss them; they will be read and answered, but merged only afterwards. The submitted state is tagged `submission` so anyone can see exactly what was entered.
- **From 9 Nov 2026**, pull requests are reviewed and merged as described below.

## How to contribute

1. **Open an issue first** for anything bigger than a typo, so we agree on the direction before you spend time.
2. **Fork** the repository and work on a branch of your fork. Direct pushes are not possible, and `main` is protected.
3. Keep each pull request **small and about one thing**.
4. Run the tests: `python -m pytest -q -W error`. Add or change tests with your code; a change that fixes a bug should include a test that failed before the fix.
5. **Sign off** every commit (`git commit -s`): the sign-off says you wrote it, or have the right to submit it, under the repository's [LICENSE](LICENSE) (the Developer Certificate of Origin). There is no other contributor agreement.
6. Fill in the pull request template honestly.

## What the maintainer checks in every pull request (so you know what to expect)

- **Safety is never weakened:** the F12 stop, the controls-card allow-list, the "only the chosen window, only when handed over" rule, the spending caps and the pinned hosts. A change here needs a very good reason and a test.
- **No secrets, no personal data:** no key, token, e-mail, local path or private screenshot, in the code, tests, fixtures or history. Push protection and a repo test also look for these.
- **Network:** no new host, no proxy or redirect support, no environment-variable override of a pinned address, without discussion first.
- **Dependencies:** each new dependency needs a reason, a licence check and a pinned version. Fewer is better.
- **Data and training:** training examples must come from our own game states, hand-written phrases, or recordings made with the player's clear consent. **No example may come from the output of an AI model** (the provider terms forbid it for some models). Every example records its origin.
- **Honest claims:** a number in the README or a results file must come from a file the code wrote; nothing is typed in by hand.
- **Tests pass** with warnings as errors, on a clean checkout, in CI.
- **Readability for beginners:** plain words, no jargon without a short explanation; Arabic and English kept as separate versions.
- **Licence and origin:** your code is yours (or properly licensed), and compatible with the repository's licence.

AI-assisted contributions are welcome **if** you say so in the pull request and you have read, understood and tested every line yourself.

## How a review works

The maintainer reads the whole diff, runs it, and may ask for changes, split it, or decline it. A decision may take several days. Declining a pull request is never a judgement of you; the project has a narrow scope and a high bar for safety.

## Reporting problems

- Bugs and ideas: open an issue (use the templates).
- **Security problems: do not open an issue**; see [SECURITY.md](SECURITY.md).
- By opening an issue you agree that what you write there is "Not a Contribution" in the sense of the licence, unless you say otherwise.

Please also read the [Code of conduct](CODE_OF_CONDUCT.md) and [Responsible use](RESPONSIBLE_USE.md).
