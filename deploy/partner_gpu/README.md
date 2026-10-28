# partner GPU service deployment of the tactical loop

`playfellow_tactical/` is a Truss that serves the tactical loop over one persistent WebSocket. The logic is in `playfellow_coop/serve/protocol.py` and is tested without a GPU
(`tests/test_serve.py`); `model/model.py` only adapts it to Truss.

**It is not deployed.** `truss push` creates a billed deployment on your partner GPU service account, so it is yours to run:

1. `pip install truss` and `truss login` (your own partner GPU service key; never commit it).
2. Fill in `Model.load` and `Model._generate` in `model/model.py` with the runtime you chose (Muse Glimmer 30B with prefix caching and speculative decoding is the plan).
3. `truss push playfellow_tactical`, then connect a client to the model's WebSocket address and send the messages described in `playfellow_coop/serve/protocol.py`.

A deployment with no model loaded answers every frame with `model_unavailable`; it never invents an action.
