# Notice

Event work for the PlayFellow engine. Copyright (c) 2026 Hesham Aboul-Fetouh. See [LICENSE](LICENSE).

The PlayFellow engine (`hesham88/playfellow`, tags `before-kickoff` and `pre-hackathon`) is a **separate, pre-existing project** with its own licence file. It is installed from a clone of the tag and is not copied into this repository.

## Built with AI assistance
This repository was built by one person with AI coding assistance, including Meta's Muse Code. AI-generated art and music used in the demo are disclosed in the demo's description.

## Acknowledgements
Inspired by research such as Google DeepMind's SIMA 2 and NVIDIA's NitroGen. No code, weights or data from either is used, and there is no affiliation or endorsement.

Method ideas we studied and re-implemented in our own code, with thanks to the authors (all Apache-2.0; no code is copied, there is no affiliation or endorsement):

| Work | What we took from it | Where it shows |
|---|---|---|
| [Elephant-Goldfish Model](https://github.com/google/elephant-goldfish-model) (Google) | The working method: one side holds the project context and drafts, a fresh reviewer who has not seen the conversation checks the document, and the person decides | `docs/` review notes; how our specs and contracts were reviewed |
| [Harness²](https://github.com/google-research/harness2) (Google Research; paper: arXiv 2610.14224) | Propose, probe and compose: edit the harness around a fixed model, test the edits on the same task, and keep what the contrasts support, with a memory of lessons that carries to the next task | `playfellow_coop/harness_loop.py`, the credit-day experiment protocol |
| [Perfetto](https://github.com/google/perfetto) (Google) | The trace format and viewer: we export our own trace as a Chrome-trace file that Perfetto opens, and the admin panel can open it there. No Perfetto code is in this repository | `playfellow_coop/trace_perfetto.py`, `demo/trace_to_perfetto.py` |
| [Agent Development Kit and its harness pages](https://adk.dev) (Google) | The four parts of a harness: sessions and state with scopes, long-term memory, tools and MCP, graph workflows with parallel checks and a retry limit, tool confirmation, safety guardrails, evaluation (code checks, model judge, human review, conformance). The ideas shape our own harness; ADK itself is used as a library only in `playfellow_coop/adk_app/` (the episode graph on ADK's runner, ADK's own evaluator on our exported evalsets, ADK's spans beside our traces), installed in an environment of its own and never by the app. No ADK code is copied into this repository | `playfellow_coop/harness/`, `playfellow_coop/adk_app/` |
| [Harness² benchmarks and experiments notes](https://github.com/google-research/harness2) | Same configuration for refine, judge and report; a run is resumed only when its configuration is equal; start small because of cost | `bench/arena_run.py` (checkpoint and resume) |
| [meta-sam](https://github.com/meta-models/meta-sam) protocol (Meta; SAM License) | The published text format of SAM 3 answers (fields by name, inclusive box edges, optional confidence). We wrote our own reader from the document; no code, test data or documentation text is copied here. Our reading is checked against the repository's shared conformance cases from a local clone kept outside this repository (`python -m playfellow_coop.sam_conformance --clone DIR`): the cases are read there, never copied or run. SAM is acknowledged here as the License asks | `playfellow_coop/sam_marks.py`, `playfellow_coop/sam_protocol.py`, `playfellow_coop/sam_conformance.py` |
| [meta-model-cookbook](https://github.com/meta-models/meta-model-cookbook) (Meta; MIT) | Best practice for the Model API: stable prompt prefix and cache key, schema-constrained replies, reasoning effort, error classes | `playfellow_coop/muse_brain.py` |

Fonts shipped in the Windows app (not in this repository): Baloo Bhaijaan 2 and Rubik, both SIL Open Font License 1.1.

## Third-party software (installed separately, not bundled)

| Package | Licence |
|---|---|
| httpx | BSD-3-Clause |
| certifi | MPL-2.0 |
| Pillow | MIT-CMU (HPND) |
| websockets | BSD-3-Clause |
| sounddevice | MIT |
| pynput | LGPL-3.0 (used through a normal pip install, not bundled) |
| PySide6 (Qt for Python; the floating panel, optional) | LGPL-3.0 (installed separately, not bundled) |
| pytest (tests) | MIT |
| google-adk with its eval extra (the ADK side only, `playfellow_coop/adk_app/`; its own environment from `requirements-adk.txt`, never needed by the app) | Apache-2.0 |
| Rust fast path (`rust/fastpath`) | our own code, written during the event; no Rust dependencies |
| the PlayFellow engine and its own dependencies | see its NOTICE |

Using an AI provider also means accepting that provider's own terms. Several of them, including the Meta Model API, require users to be 18 or older.
