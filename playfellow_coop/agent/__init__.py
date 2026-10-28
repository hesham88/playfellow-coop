"""How the agent learns the rules of a game it has never seen, without changing any model weights (research R3 section 6, stages 2 to 4):

  beliefs      EvoBelief: a fast episode-local state and a slow store of evidence-linked rules; a surprise opens an experiment; a rule is only trusted after the evidence says so, and is
               narrowed or demoted the moment a counterexample appears (so a silent change of the game's rules is noticed and re-learned)
  worldmodel   Tycho: a model-written program (init_state, transition, render) that is checked against what was really seen, used to look ahead in memory, and repaired when it is wrong;
               an orchestrator decides when that is worth the model calls
  context      Algorithm Distillation in spirit: short summaries of earlier episodes kept in order of improvement, so the next attempt starts from what the last ones learned
"""
