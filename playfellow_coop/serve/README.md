# serve

Serving the tactical loop: the WebSocket session logic (protocol.py) and the model routing matrix (routing.py).

## Files

- `protocol.py`: The tactical loop over one persistent WebSocket (research R1 section 1.3 and 4.1): frames in, action chunks out, one connection pinned to one replica so the prompt prefix stays cached.
- `routing.py`: Which model for which job (research R1 section 1.1): five models, each with a different latency, price and privacy profile, and a router that picks by role and constraints.
