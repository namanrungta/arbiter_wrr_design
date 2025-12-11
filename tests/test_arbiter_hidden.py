import os
import random
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotb_tools.runner import get_runner

# -----------------------------------------------------------------------------
# HELPER FUNCTIONS
# -----------------------------------------------------------------------------

def get_grant_index(o_gnt_val, num_clients):
    """
    Decodes one-hot grant signal to integer index.
    Returns -1 if no grant or multiple grants (error).
    """
    val = int(o_gnt_val)
    if val == 0:
        return -1
    
    # Check for one-hot
    if (val & (val - 1)) != 0:
        return -2 # Error: Multiple grants
        
    # Decode
    for i in range(num_clients):
        if (val >> i) & 1:
            return i
    return -1

async def reset_dut(dut):
    """Standard asynchronous reset"""
    dut.rst_n.value = 0
    dut.i_req.value = 0
    dut.i_lock.value = 0
    dut.i_weight.value = 0
    await Timer(20, units="ns")
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

def pack_weights(weights, width):
    """Packs a list of integers into a single signal value"""
    packed_val = 0
    for i, w in enumerate(weights):
        packed_val |= (w & ((1 << width) - 1)) << (i * width)
    return packed_val

# -----------------------------------------------------------------------------
# MAIN TEST
# -----------------------------------------------------------------------------

@cocotb.test()
async def test_arbiter_wrr_lock(dut):
    """
    Hidden Grader for Weighted Round Robin Arbiter.
    Tests specific failure modes:
    1. Basic Rotation
    2. Weighted Fairness
    3. Work Conservation (Early Drop)
    4. Illegal Lock (Lock stealing)
    5. Lock-to-Switch Transition
    """
    
    # --- Setup ---
    NUM_CLIENTS = 4
    WEIGHT_WIDTH = 4
    
    # Start Clock
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    
    await reset_dut(dut)
    
    dut._log.info("--- Test Phase 1: Basic Round Robin (Weights=0) ---")
    # All weights 0 => 1 cycle per turn
    dut.i_weight.value = pack_weights([0, 0, 0, 0], WEIGHT_WIDTH)
    dut.i_req.value = 0xF # All requesting
    
    # Wait for initial grant (1 cycle latency for registered outputs)
    await RisingEdge(dut.clk) 
    await RisingEdge(dut.clk)
    
    # Sequence should be 0 -> 1 -> 2 -> 3 -> 0
    expected_sequence = [0, 1, 2, 3, 0]
    
    for expected_id in expected_sequence:
        gnt_idx = get_grant_index(dut.o_gnt.value, NUM_CLIENTS)
        assert gnt_idx == expected_id, \
            f"[Phase 1] Expected Grant: {expected_id}, Got: {gnt_idx}. Basic rotation failed."
        await RisingEdge(dut.clk)

    dut._log.info("--- Test Phase 2: Weighted Fairness ---")
    # Weights: 
    # Client 0: 1 (Total 2 cycles)
    # Client 1: 3 (Total 4 cycles)
    # Client 2: 0 (Total 1 cycle)
    # Client 3: 0 (Total 1 cycle)
    dut.i_weight.value = pack_weights([1, 3, 0, 0], WEIGHT_WIDTH)
    
    # We are currently at the start of Client 0's turn (from previous loop end)
    # Reset to known state to be safe or just continue. Let's Reset.
    await reset_dut(dut)
    dut.i_weight.value = pack_weights([1, 3, 0, 0], WEIGHT_WIDTH)
    dut.i_req.value = 0xF
    await RisingEdge(dut.clk) # Register reset
    await RisingEdge(dut.clk) # Initial arbitration decision
    
    # Client 0 should hold for 2 cycles
    assert get_grant_index(dut.o_gnt.value, NUM_CLIENTS) == 0, "Phase 2 Start: Client 0 not granted"
    await RisingEdge(dut.clk) 
    assert get_grant_index(dut.o_gnt.value, NUM_CLIENTS) == 0, "Phase 2: Client 0 dropped grant too early"
    await RisingEdge(dut.clk)
    
    # Now should be Client 1 (for 4 cycles)
    assert get_grant_index(dut.o_gnt.value, NUM_CLIENTS) == 1, "Phase 2: Failed to switch to Client 1"
    for _ in range(3):
        await RisingEdge(dut.clk)
        assert get_grant_index(dut.o_gnt.value, NUM_CLIENTS) == 1, "Phase 2: Client 1 dropped grant too early"
    
    await RisingEdge(dut.clk)
    # Now should be Client 2
    assert get_grant_index(dut.o_gnt.value, NUM_CLIENTS) == 2, "Phase 2: Failed to switch to Client 2"

    dut._log.info("--- Test Phase 3: Work Conservation (Early Drop) ---")
    
    await reset_dut(dut)
    dut.i_weight.value = pack_weights([15, 0, 0, 0], WEIGHT_WIDTH)
    dut.i_req.value = 0x3 
    
    await RisingEdge(dut.clk) 
    await RisingEdge(dut.clk)
    
    # Client 0 Granted
    assert get_grant_index(dut.o_gnt.value, NUM_CLIENTS) == 0, "Phase 3: Client 0 start"
    
    # Client 0 drops request immediately
    dut.i_req.value = 0x2 
    
    
    await RisingEdge(dut.clk)
    
    # --- FIX: Add this small delay ---
    await Timer(1, units="ns") 
    # This allows combinational logic (keep_current) to settle to 0 
    # BEFORE the clock edge samples it.
    
    # Logic should IMMEDIATELY switch to Client 1.
    gnt = get_grant_index(dut.o_gnt.value, NUM_CLIENTS)
    assert gnt == 1, f"Phase 3: Violation. Expected Clt 1, Got {gnt}."

    dut._log.info("--- Test Phase 4: Atomic Lock ---")
    # Client 0 locks. Should hold grant longer than weight.
    
    await reset_dut(dut)
    dut.i_weight.value = 0 # Weight 0 (1 cycle default)
    dut.i_req.value = 0x3  # Clt 0 and 1
    
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    
    assert get_grant_index(dut.o_gnt.value, NUM_CLIENTS) == 0
    
    # Assert Lock
    dut.i_lock.value = 0x1 # Client 0 locks
    
    # Hold for 10 cycles (way past weight of 0)
    for i in range(10):
        await RisingEdge(dut.clk)
        # --- FIX: Add this small delay ---
        await Timer(1, units="ns") 
        # This allows combinational logic (keep_current) to settle to 0 
        # BEFORE the clock edge samples it.
        assert get_grant_index(dut.o_gnt.value, NUM_CLIENTS) == 0, f"Phase 4: Lock lost at cycle {i}"
        
    # Release Lock
    dut.i_lock.value = 0x0
    await RisingEdge(dut.clk)
    
    # --- FIX: Add this small delay ---
    await Timer(1, units="ns") 
    # This allows combinational logic (keep_current) to settle to 0 
    # BEFORE the clock edge samples it.
    
    # Should switch to Client 1
    assert get_grant_index(dut.o_gnt.value, NUM_CLIENTS) == 1, "Phase 4: Failed to release lock"

    dut._log.info("--- Test Phase 5: The 'Illegal Lock' Trap ---")
    # Client 1 tries to 'steal' the bus from Client 0 using lock.
    
    await reset_dut(dut)
    dut.i_weight.value = pack_weights([5, 0, 0, 0], WEIGHT_WIDTH) # Clt 0 has 6 cycles
    dut.i_req.value = 0x3
    
    await RisingEdge(dut.clk) 
    await RisingEdge(dut.clk)
    
    assert get_grant_index(dut.o_gnt.value, NUM_CLIENTS) == 0
    
    # Client 1 asserts lock (Illegal!)
    dut.i_lock.value = 0x2 
    
    # Client 0 should KEEP the grant because it has weight credits left.
    await RisingEdge(dut.clk)
    gnt = get_grant_index(dut.o_gnt.value, NUM_CLIENTS)
    assert gnt == 0, f"Phase 5: Illegal Lock succeeded! Clt 0 lost grant to {gnt}."

    dut._log.info("--- Test Phase 6: Lock-to-Switch Transition ---")
    # If we lock for 100 cycles, and weight was 2, we must switch immediately on unlock.
    # LLMs often "reset" the counter on unlock, giving the agent free extra cycles.
    
    await reset_dut(dut)
    dut.i_weight.value = pack_weights([1, 0, 0, 0], WEIGHT_WIDTH) # Clt 0 has 2 cycles
    dut.i_req.value = 0x3
    
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    
    # Assert Lock immediately
    dut.i_lock.value = 0x1 
    
    # Hold for 5 cycles
    for _ in range(5):
        await RisingEdge(dut.clk)
        
    # Release Lock
    dut.i_lock.value = 0x0
    await RisingEdge(dut.clk)
    
    # --- FIX: Add this small delay ---
    await Timer(1, units="ns") 
    # This allows combinational logic (keep_current) to settle to 0 
    # BEFORE the clock edge samples it.
    
    # Since we used 5 cycles ( > 2 allowed), we must switch IMMEDIATELY.
    # If the logic reloaded the counter on unlock, it would stay at 0.
    gnt = get_grant_index(dut.o_gnt.value, NUM_CLIENTS)
    assert gnt == 1, f"Phase 6: Failed to switch after lock. Did you reload the counter?"

    dut._log.info("All Hidden Tests Passed!")

# -----------------------------------------------------------------------------
# PYTEST RUNNER (REQUIRED FOR HUD)
# -----------------------------------------------------------------------------

def test_arbiter_hidden_runner():
    """
    Pytest wrapper to run the cocotb test.
    This is required for the HUD evaluation framework to discover the test.
    """
    sim = os.getenv("SIM", "icarus")
    
    # Path to sources - adjusting for standard structure
    # Expected structure:
    # /repo/
    #   sources/arbiter_wrr_lock.sv
    #   tests/test_arbiter_hidden.py
    
    proj_path = Path(__file__).resolve().parent.parent
    sources = [proj_path / "sources/arbiter_wrr_lock.sv"]

    runner = get_runner(sim)
    
    runner.build(
        sources=sources,
        hdl_toplevel="arbiter_wrr_lock",
        always=True,
    )

    runner.test(
        hdl_toplevel="arbiter_wrr_lock",
        test_module="test_arbiter_hidden", # Matches filename without .py
        waves=True # Useful for debugging if needed
    )
