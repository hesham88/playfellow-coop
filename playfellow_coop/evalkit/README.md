# evalkit

Evaluation done honestly: statistics, attribution, the rung ladder, LSIAP measures, the cost model and the reproducibility receipt.

## Files

- `attribution.py`: Who did the playing? The honest attribution protocol (research R1 section 3.5, R2 section 6).
- `costmodel.py`: The calls-per-win and cost-per-win model (research R2 section 5.2, R1 section 3.4): which optimisation lever cuts what.
- `isolation.py`: Keep an evaluation clean (Harness², research R5): no network while a candidate harness is being tried, an always-on prompt that stays small, and a record of what the search cost.
- `ladder.py`: The evaluation ladder: which help each rung allows and which clock it runs on (research R1 section 3.5 "4-rung ladder", R2 section 6.1 "five tiers").
- `lsiap.py`: LSIAP: Level, Speed, Intelligence, Accuracy, Overall performance (research R3 section 4), as numbers a report can carry.
- `receipt.py`: The reproducibility receipt every evaluation log carries (research R2 section 6.2): enough to repeat the run and to see exactly what help was present.
- `stats.py`: Statistics a benchmark report must carry (research R3 section 4.5, R1 section 3.5): the rliable methodology in plain numpy, Glass's delta, harness lift and budgeted success.
