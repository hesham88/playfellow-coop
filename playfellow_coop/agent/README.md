# agent

How the agent learns the rules of a game it has never seen, without changing any model weights (research R3 section 6, stages 2 to 4):

## Files

- `beliefs.py`: EvoBelief: learn the rules of a new game by running small experiments, and notice when a rule stops being true (research R3 section 6.2).
- `context.py`: What the last attempts learned, in a form the next attempt can read (Algorithm Distillation in spirit, research R3 section 6.4).
- `worldmodel.py`: Tycho: a model-written program as a world model, checked against reality, used to look ahead, repaired when wrong (research R3 section 6.3).
