# arbiter_wrr_lock (HUD)

Weighted round robin arbiter with atomic lock support, formatted for the HUD evaluation framework.

## Structure
- `sources/` — SystemVerilog RTL (`arbiter_wrr_lock.sv`)
- `tests/` — Hidden cocotb test with required pytest wrapper
- `docs/Specification.md` — Behavioral spec
- `prompt.txt` — Task prompt for the agent

## Quick start
Install deps and run the hidden test locally (optional):
```
uv pip install -e .
pytest tests/test_arbiter_hidden.py -v
```

