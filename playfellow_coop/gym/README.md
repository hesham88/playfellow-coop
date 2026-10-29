# gym

Environments, rewards and oracles: the gyms the benchmarks and the self-improvement loops run on.

## Files

- `env.py`: A Gymnasium-style environment over any arena game (the plain pack or the revamped glass games): pixels in, keys out, a dense and COMPLETE reward.
- `obs.py`: From pixels to the structured observation a model-written skill reads (research R1 section 3.3: "the generated method receives pre-parsed normalised coordinates").
- `oracle.py`: The oracle: the best local controller we have for each game, driven through the gym with pictures only, and the checks that a gym's reward is complete.
- `progress.py`: A 0 to 1 progress score per game, from the game's own progress() numbers: how far it got, never how to win.
