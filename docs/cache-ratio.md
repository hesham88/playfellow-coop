# Prompt cache: how much each paid run reused (INF1)

Measured from the saved result files by `tools/cache_ratio.py` ($0, no network). Cached share = cached input tokens / all input tokens, with a 95 percent interval from a paired bootstrap over episodes. Dollars at the documented muse-spark Standard prices (cached input $0.15, input $1.25, output $4.25 per million); no documented price, no dollar figure.

| file | brain / model | episodes | calls | calls after an episode's first | input tokens | cached | cached share (95%) | recorded by our budget | at documented prices | saved by the cache |
|---|---|---|---|---|---|---|---|---|---|---|
| `results/glass/muse-skills-20261029.json` | muse / muse-spark-1.3 | 15 | 15 | 0% | 21,579 | 12,394 | 57.4% (35.3% to 78.2%) | $0.0422 | $0.0285 | $0.0136 |
| `results/unseen/muse-raw-20261027.json` | muse / muse-spark-1.3 | 15 | 289 | 95% | 548,607 | 285,472 | 52.0% (50.5% to 53.8%) | $1.1877 | $0.8737 | $0.3140 |
| `results/unseen/open-raw-20261027.json` | open / meta-models/muse-spark-open-1026 | 15 | 226 | 93% | 439,805 | 223,744 | 50.9% (49.5% to 52.3%) | $1.0184 | no documented price | n/a |

Reading it:
- Only calls after an episode's first one can reuse that episode's prompt prefix; a run of one call per episode can hit the cache only across episodes.
- Our budget prices every input token at the full rate, so its recorded dollars are an upper bound whenever the cache hit (safe for the spending cap, too high as a cost report); the documented-price column is what the provider's own price list gives for the same tokens.
