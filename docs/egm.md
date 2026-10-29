# How we work: the Elephant-Goldfish Model (EGM), adopted in full

Source: Dave Rensin, "Elephants, Goldfish and the New Golden Age of Software Engineering" (Medium, 27 April 2026), and the open-source plugin published by Google (`github.com/google/elephant-goldfish-model`, Apache-2.0). We follow the method and write our own skills and templates; no plugin code is copied (see `NOTICE.md`).

The idea in one line: **design is the new code.** The design document is the source of truth, and it is tested on readers who start with nothing.

- **Elephant**: the long, context-rich working session and the design document it produces. It holds the reasons.
- **Goldfish**: a fresh reader with zero memory of the conversation. It sees only the document and the files the document names.
- **The owner** makes the architecture decisions and approves the result. A model never outsources that judgment.

## The rules that apply to every step

1. **No code during design.** Design is prose and block diagrams; short pseudocode is allowed. Code starts only after readiness passes.
2. **The model proposes the first design**, so a blind spot shows up as a wrong proposal, not as a design the author already believed.
3. **Challenge, do not flatter.** No praise words, no apologies, no agreement without a reason. If a reviewer starts agreeing, tell it that agreeing is not helpful.
4. **Artifact first.** Long outputs go to files; chat carries a link and the two or three points that matter.
5. **Plain English.** No jargon, no promotional adjectives. A newcomer must be able to follow it.
6. **Findings carry a severity:** Blocker (cannot build or ship), Major (will cause rework or a wrong result), Nit (taste). Reviews are read-only: a reviewer writes findings and never edits the author's files.
7. **One question at a time** when the owner must decide, with up to three options and their trade-offs.
8. **Convergence cap:** each review stage gets one re-run after edits. The loop ends when findings fall to nits.

## The nine steps

| Phase | Step | What happens | Where it lands |
|---|---|---|---|
| 1 Grow the elephant | 1 Context | A fresh session reads the READMEs and the files the task touches and says what it understood; correct it at once | the hierarchy of `README.md` files |
| | 2 No-code rule | A design discussion: questions and challenges for 20 to 30 minutes, not code | `docs/designs/<name>/brief.md` |
| | 3 Sycophant challenge | When the model agrees too easily, say "your best use is to challenge my thinking" | |
| | 4 First draft | The model proposes the technical approach in prose, the owner argues with it | |
| 2 Teach the elephant | Write the document | Written one section at a time, in this order: **Problem** (3 to 5 sentences), **Technical Plan** (components and how they fit, a block diagram), **Alternatives** (what was ruled out and why: guardrails against later arguments), **Detailed Implementation** (every file created, changed or deleted, with the reason) | `docs/designs/<name>/design.md` |
| 3 Goldfish protocol | 5 Comprehension test | A fresh session reads the document and the files it names and says what it is for and how the system works. If it cannot, the document is missing context | `reviews/comprehension.md` |
| | 6 Critic review | A fresh expert reviewer lists missed edge cases, faulty assumptions and ambiguities (about 30 percent of findings are worth acting on); repeat until nits | `reviews/critic.md` |
| | 7 Implementation readiness | A fresh engineer answers: does this contain everything needed to implement it in one pass? Questions get answered in the document | `reviews/readiness.md` |
| 4 Implementation | 8 Guarded coding | "Read the design and the files it names. Implement it exactly." A crashed session restarts from the document | the code and its tests |
| | 9 Mean code review | A fresh reviewer is told the code is poor and must say every way it is; repeat until the criticism is trivial | `reviews/code.md` |

## The reviewer lenses

For a concept (before the draft), six lenses: contrarian (can existing tools do ninety percent of it?), cost and tokens (peak load, quotas, dollars), user experience (is it clear, are errors actionable?), migration and compatibility (what breaks?), observability (can it be traced at 3 AM?), tech debt (will it hurt in two years?).

For a design document, the stages the plugin runs: zoom out (structure), comprehension, critic (design, structure, style), a second zoom out, and implementation readiness. Our extra lenses: **the player's safety** (keys only from the controls card; F12 always works), **honesty** (a result is only a result when a file written by the code backs it), **no old UI** (everything is tested on the new look), **secrets** (nothing sensitive in a file or a log).

## Peanuts and hay: READMEs as the elephant's food

A model reads a tree of short `README.md` files faster and more reliably than the source. Each package folder has one: what the folder is for, and one line per file. They are written bottom-up, checked by a person, and rolled up level by level. A README may be deleted once every file is named and lightly explained in some design document. `tools/peanuts.py` rebuilds the draft list of files from each module's own first docstring line; a person fixes the wording.

## Onboarding

A new person reads the README tree and the design documents in a notebook, then writes a design document for their first change. When it passes the goldfish test they can contribute.

## What we do about "who is the goldfish"

A goldfish has to be a session that has never seen the conversation. Our options, in order: (1) a fresh session started by the owner or by a second assistant that reads only the files; (2) a fresh read-only reviewer started for one document at a time. The reviewer gets the document path, the lens and the severity vocabulary, and nothing else; it writes findings to the reviews folder. It is never given the author's reasoning, because the point is to find what the document fails to say.
