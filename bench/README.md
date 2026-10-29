# bench

The `bench` folder.

## Files

- `arena_run.py`: Play an arena game headless with any brain, many seeds, and write one results file: the benchmark behind the unseen-games test and the credit-day stages.
- `fastpath_bench.py`: Times the Rust fast path against its Python twin and writes ONE pf-results/1 file with only measured numbers.
- `fit_states.py`: Build time: fit the screen-state classifier for each arena game that has a skill and save it beside the code, with a held-out check.
- `open_weights_brain.py`: The open-weights bench brain: the same harness, schema and safety as the Muse brain, pointed at an open-weights Muse Spark served by a partner GPU service.
- `run_condition.py`: Run one benchmark condition over several games and seeds and write one results file.
- `speed_bench.py`: Run the speed bench: `python bench/speed_bench.py --brain builtin --turns 30`.
