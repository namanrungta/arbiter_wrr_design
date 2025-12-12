import random
import os
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotb_tools.runner import get_runner

# -----------------------------------------------------------------------------
# SHARED HELPERS & MODEL
# -----------------------------------------------------------------------------

class ArbiterModel:
    def __init__(self, num_clients, weight_width):
        self.num_clients = num_clients
        self.weight_width = weight_width
        self.rr_ptr = 0           
        self.current_gnt = None   
        self.counter = 0          

    def predict_next(self, req_vec, lock_vec, weights_list):
        next_gnt = self.current_gnt
        
        # 1. Check Current Owner Status
        if self.current_gnt is not None:
            # Work Conservation (Spec 3.4)
            if not ((req_vec >> self.current_gnt) & 1):
                next_gnt = None
            else:
                is_locked = (lock_vec >> self.current_gnt) & 1
                if is_locked:
                    # Lock Logic (Spec 3.3): Hold, decrement counter if > 0
                    if self.counter > 0: self.counter -= 1
                else:
                    if self.counter > 0:
                        self.counter -= 1
                    else:
                        next_gnt = None # Exhausted

        # 2. Arbitration (if idle)
        if next_gnt is None:
            if self.current_gnt is not None:
                self.rr_ptr = (self.current_gnt + 1) % self.num_clients
                self.current_gnt = None 
            
            for i in range(self.num_clients):
                candidate = (self.rr_ptr + i) % self.num_clients
                if (req_vec >> candidate) & 1:
                    next_gnt = candidate
                    self.counter = weights_list[candidate]
                    break
        
        self.current_gnt = next_gnt
        return next_gnt

def get_grant_index(o_gnt_val, num_clients):
    try:
        val = int(o_gnt_val)
    except ValueError:
        return -1 
    if val == 0: return -1
    if (val & (val - 1)) != 0: return -2 
    for i in range(num_clients):
        if (val >> i) & 1: return i
    return -1

def pack_weights(weights, width):
    packed_val = 0
    for i, w in enumerate(weights):
        packed_val |= (w & ((1 << width) - 1)) << (i * width)
    return packed_val

async def setup_dut(dut):
    """Starts clock, resets DUT, and reads parameters."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    try:
        N = int(dut.NUM_CLIENTS.value)
        W = int(dut.WEIGHT_WIDTH.value)
    except:
        N, W = 4, 4
        
    dut.rst_n.value = 0
    dut.i_req.value = 0
    dut.i_lock.value = 0
    dut.i_weight.value = 0
    
    await Timer(20, unit="ns")
    dut.rst_n.value = 1
    await RisingEdge(dut.clk) # Consumes the Reset Release edge
    return N, W

# -----------------------------------------------------------------------------
# INDIVIDUAL TEST SCENARIOS
# -----------------------------------------------------------------------------

@cocotb.test()
async def test_01_basic_rotation(dut):
    """Scenario: Verify basic Round Robin rotation when weights are 0."""
    N, W = await setup_dut(dut)
    
    dut.i_weight.value = pack_weights([0]*N, W)
    dut.i_req.value = (1 << N) - 1 

    # REMOVED: Extra await RisingEdge(dut.clk) here.
    # The first await inside the loop will act as the first cycle check.

    for i in range(N + 1):
        expected_id = i % N
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns") 
        
        gnt = get_grant_index(dut.o_gnt.value, N)
        assert gnt == expected_id, \
            f"Cycle {i}: Expected Grant {expected_id}, Got {gnt}"

@cocotb.test()
async def test_02_weighted_fairness(dut):
    """Scenario: Verify clients hold grant for (Weight + 1) cycles."""
    N, W = await setup_dut(dut)
    
    weights = [1, 3, 0, 0] 
    if N > 4: weights += [0] * (N-4)
    dut.i_weight.value = pack_weights(weights, W)
    dut.i_req.value = (1 << N) - 1
    
    # REMOVED: Extra await RisingEdge(dut.clk) here.
    
    # C0 (Weight 1 -> 2 cycles)
    await RisingEdge(dut.clk) # Cycle 1
    await Timer(1, unit="ns")
    assert get_grant_index(dut.o_gnt.value, N) == 0, "C0 failed to start"
    
    await RisingEdge(dut.clk) # Cycle 2
    await Timer(1, unit="ns")
    assert get_grant_index(dut.o_gnt.value, N) == 0, "C0 failed to hold 2nd cycle"
    
    # C1 (Weight 3 -> 4 cycles)
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert get_grant_index(dut.o_gnt.value, N) == 1, "Failed switch to C1"
    
    for i in range(3):
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        assert get_grant_index(dut.o_gnt.value, N) == 1, f"C1 dropped early at cycle {i+2}"
        
    # C2 (Weight 0 -> 1 cycle)
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert get_grant_index(dut.o_gnt.value, N) == 2, "Failed switch to C2"

@cocotb.test()
async def test_03_work_conservation(dut):
    """Scenario: Early Termination."""
    N, W = await setup_dut(dut)
    
    dut.i_weight.value = pack_weights([15]*N, W)
    dut.i_req.value = 0x3 # C0 & C1
    
    await RisingEdge(dut.clk) 
    await Timer(1, unit="ns")
    assert get_grant_index(dut.o_gnt.value, N) == 0
    
    # Drop Request
    dut.i_req.value = 0x2 
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    
    gnt = get_grant_index(dut.o_gnt.value, N)
    assert gnt == 1, f"Work Conservation failed. Expected C1, got {gnt}"

@cocotb.test()
async def test_04_atomic_lock_logic(dut):
    """Scenario: Atomic Lock holding."""
    N, W = await setup_dut(dut)
    
    dut.i_weight.value = 0 
    dut.i_req.value = 0x3
    
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert get_grant_index(dut.o_gnt.value, N) == 0
    
    # Assert Lock
    dut.i_lock.value = 0x1
    
    # Hold for 10 cycles
    for i in range(10):
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        assert get_grant_index(dut.o_gnt.value, N) == 0, f"Lost grant while locked at cycle {i}"
        
    # Release Lock
    dut.i_lock.value = 0x0
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    
    assert get_grant_index(dut.o_gnt.value, N) == 1, "Failed to release after unlock"

@cocotb.test()
async def test_05_illegal_lock_attempt(dut):
    """Scenario: Lock stealing prevention."""
    N, W = await setup_dut(dut)
    
    dut.i_weight.value = pack_weights([5]*N, W) 
    dut.i_req.value = 0x3
    
    await RisingEdge(dut.clk) # C0 Granted
    
    # Illegal Action: Client 1 asserts lock
    dut.i_lock.value = 0x2 
    
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    
    gnt = get_grant_index(dut.o_gnt.value, N)
    assert gnt == 0, f"Illegal Lock Succeeded! C0 lost bus to {gnt}"

@cocotb.test()
async def test_06_boundary_lock_extension(dut):
    """Scenario: Lock at Counter=0 boundary."""
    N, W = await setup_dut(dut)
    dut.i_weight.value = 0 
    dut.i_req.value = 0x3
    
    await RisingEdge(dut.clk) 
    
    # Assert Lock NOW (Counter is 0)
    dut.i_lock.value = 0x1
    
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    
    assert get_grant_index(dut.o_gnt.value, N) == 0, "Lock failed to extend at Counter=0 boundary"

@cocotb.test()
async def test_07_randomized_stress(dut):
    """Scenario: Randomized stimulus vs Model."""
    N, W = await setup_dut(dut)
    model = ArbiterModel(N, W)
    
    dut.i_weight.value = pack_weights([random.randint(0, (1<<W)-1) for _ in range(N)], W)
    current_weights = [0]*N 
    
    # Sync Model
    model.rr_ptr = 0 # Matches RTL reset state
    
    for cycle in range(2000):
        # 1. Randomize Inputs
        req_vec = 0
        lock_vec = 0
        for i in range(N):
            if random.random() > 0.1: req_vec |= (1 << i)
            if random.random() > 0.95: lock_vec |= (1 << i)
            
        if cycle % 100 == 0:
            current_weights = [random.randint(0, (1<<W)-1) for _ in range(N)]
            dut.i_weight.value = pack_weights(current_weights, W)
            
        # Drive DUT
        dut.i_req.value = req_vec
        dut.i_lock.value = lock_vec
        
        # 2. Predict (using the inputs we just set)
        expected = model.predict_next(req_vec, lock_vec, current_weights)
        
        # 3. Step
        await RisingEdge(dut.clk)
        
        # 4. Compare (Use Timer to settle)
        await Timer(1, unit="ns") 
        
        actual = get_grant_index(dut.o_gnt.value, N)
        
        if expected is None and actual == -1: continue
        
        # Debug info
        if actual != expected:
            dut._log.error(f"FAIL Cycle {cycle}: Model {expected} != DUT {actual}")
            dut._log.error(f"Inputs: Req={bin(req_vec)} Lock={bin(lock_vec)}")
            dut._log.error(f"Model State: Ptr={model.rr_ptr} Cnt={model.counter}")
            
        assert actual == expected

# -----------------------------------------------------------------------------
# RUNNER
# -----------------------------------------------------------------------------

def test_arbiter_hidden_runner():
    """Pytest wrapper."""
    sim = os.getenv("SIM", "icarus")
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
        test_module="test_arbiter_hidden", 
        waves=True 
    )