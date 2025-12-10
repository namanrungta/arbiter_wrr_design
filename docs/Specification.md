Weighted Round Robin Arbiter with Lock (arbiter_wrr_lock)

## 1. Introduction
The `arbiter_wrr_lock` is a centralized arbitration unit designed for shared bus systems. It replaces standard fair arbitration with a weighted scheme, allowing high-bandwidth agents (like DMA controllers) to hold the bus longer than low-bandwidth agents (like configuration masters). Additionally, it provides a locking mechanism for atomic Read-Modify-Write (RMW) sequences.

## 2. Interface Definition

| Signal Name | Direction | Width                          | Description                                                                          |
| :---        | :---      | :---                           | :---                                                                                 |
| `clk`       | Input     | 1                              | System clock (rising edge triggered).                                                |
| `rst_n`     | Input     | 1                              | Active-low asynchronous reset. Resets internal state and grants.                     |
| `i_req`     | Input     | `NUM_CLIENTS`                  | Active-high request vector. Bit `i` represents a request from Client `i`.            |
| `i_lock`    | Input     | `NUM_CLIENTS`                  | Active-high lock vector. Bit `i` indicates Client `i` wants to lock the arbitration. |
| `i_weight`  | Input     | `NUM_CLIENTS` * `WEIGHT_WIDTH` | Packed configuration vector containing weights for all clients.                      |
| `o_gnt`     | Output    | `NUM_CLIENTS`                  | One-hot grant vector. Bit `i` indicates Client `i` has won arbitration.              |

### 2.1 Parameters

| Parameter      | Default | Description                                                                     |
| :---           | :---    | :---                                                                            |
| `NUM_CLIENTS`  | 4       | Number of competing clients.                                                    |
| `WEIGHT_WIDTH` | 4       | Bit-width for the weight counter (max weight = $2^{\text{WEIGHT\_WIDTH}} - 1$). |

### 2.2 Weight Vector Format
The `i_weight` input is a packed array.
* Bits `[WEIGHT_WIDTH-1 : 0]` $\rightarrow$ Weight for Client 0.
* Bits `[2*WEIGHT_WIDTH-1 : WEIGHT_WIDTH]` $\rightarrow$ Weight for Client 1.
* ...and so on.

## 3. Functional Description

### 3.1 Round Robin Rotation
* The arbiter maintains a priority pointer that rotates in a fixed order: $0 \rightarrow 1 \rightarrow \dots \rightarrow N-1 \rightarrow 0$.
* Upon reset, the priority pointer points to Client 0.

### 3.2 Weighted Grant Duration
* Each client is assigned a weight $W$.
* The weight $W$ defines the **additional** number of cycles a client may hold the grant *after* the initial cycle.
    * **Total Grant Duration** = $W + 1$ cycles.
    * Example: If $W=0$, the client gets 1 cycle. If $W=3$, the client gets 4 cycles.
* When a client is newly granted the bus, an internal down-counter is loaded with its weight $W$.
* The counter decrements by 1 for every subsequent cycle the client continues to assert `i_req`.

### 3.3 Atomic Lock Behavior
The `i_lock` signal allows a client to override the weight counter.
1.  **Activation:** If the **currently granted** client asserts `i_lock` (high), the arbiter **must not** switch ownership, even if the weight counter reaches zero.
2.  **Indefinite Hold:** The client retains the grant as long as `i_req` AND `i_lock` are high.
3.  **Strict Ownership:**
    * A client can only lock the bus if it **already holds the grant**.
    * `i_lock` signals from clients who do *not* hold the grant must be ignored (masked).
4.  **Release:** When `i_lock` is de-asserted:
    * If the internal weight counter is already zero (exhausted during the lock), the arbiter must rotate to the next client immediately (on the next clock edge).
    * If the weight counter is $>0$, the client continues using its remaining credits.

### 3.4 Work Conservation (Early Termination)
To maximize bandwidth, the arbiter must not waste cycles.
* **Rule:** If the currently granted client de-asserts `i_req` (goes low), the grant must be terminated **immediately**, regardless of the remaining weight count or lock status.
* **Switching:** The arbiter must evaluate the next requesting client and update `o_gnt` on the very next clock edge.
* **Credit Reset:** If a client gives up the grant early, its remaining credits are voided. It does not "save" them for later.

## 4. Timing & State Logic
* **Registered Outputs:** The `o_gnt` signal must be the output of a flip-flop.
* **Latencies:**
    * Request to Grant: 1 cycle.
    * Grant Handover: 1 cycle (from Client A `o_gnt` low to Client B `o_gnt` high).

## 5. Edge Case Examples

| Scenario           | Current State                        | Input Change        | Expected Behavior                                                  |
| :---               | :---                                 | :---                | :---                                                               |
| **Early Drop**     | Client 0 Granted (Counter=5)         | `i_req[0]` $\to$ 0  | Arbiter switches to next requestor immediately. Counter discarded. |
| **Illegal Lock**   | Client 0 Granted                     | `i_lock[1]` $\to$ 1 | Ignored. Client 1 cannot force a switch or lock the bus.           |
| **Lock Extension** | Client 0 Granted (Counter=0)         | `i_lock[0]` $\to$ 1 | Client 0 retains grant despite Counter=0.                          |
| **Lock Release**   | Client 0 Granted (Counter=0, Locked) | `i_lock[0]` $\to$ 0 | Arbiter switches to next requestor immediately.                    |