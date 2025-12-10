`default_nettype none`

module arbiter_wrr_lock #(
    parameter int NUM_CLIENTS  = 4,
    parameter int WEIGHT_WIDTH = 4
) (
    input  wire                                         clk,
    input  wire                                         rst_n,
    
    // Client Interface
    input  wire [NUM_CLIENTS-1:0]                       i_req,
    input  wire [NUM_CLIENTS-1:0]                       i_lock,
    
    // Configuration (Packed array)
    // Format: [ (CLIENT_N_W).. | .. | (CLIENT_1_W) | (CLIENT_0_W) ]
    input  wire [NUM_CLIENTS*WEIGHT_WIDTH-1:0]          i_weight,
    
    // Output Grant (One-Hot)
    output logic [NUM_CLIENTS-1:0]                      o_gnt
);

    // -------------------------------------------------------------------------
    // Signal Declarations
    // -------------------------------------------------------------------------
    
    // Unpacked weights for easier indexing
    logic [WEIGHT_WIDTH-1:0] weight_array [NUM_CLIENTS];
    
    // State Registers
    logic [NUM_CLIENTS-1:0]          current_gnt;
    logic [$clog2(NUM_CLIENTS)-1:0]  current_ptr;
    logic [WEIGHT_WIDTH-1:0]         weight_cnt;
    logic                            is_active;

    // Next State Logic
    logic                            keep_current;
    logic                            found_next;
    logic [$clog2(NUM_CLIENTS)-1:0]  next_ptr_search;
    logic [NUM_CLIENTS-1:0]          next_gnt_search;

    // -------------------------------------------------------------------------
    // Unpack Weights
    // -------------------------------------------------------------------------
    always_comb begin
        for (int i = 0; i < NUM_CLIENTS; i++) begin
            weight_array[i] = i_weight[(i*WEIGHT_WIDTH) +: WEIGHT_WIDTH];
        end
    end

    // -------------------------------------------------------------------------
    // Arbitration Logic
    // -------------------------------------------------------------------------

    // 1. Check if the Current Owner keeps the grant
    // Rule: Must be requesting AND (Locked OR Credits Remaining)
    // Note: Only i_lock[current_ptr] is checked. Illegal locks from others are ignored.
    // Note: weight_cnt > 0 means we have at least 1 cycle left AFTER this one.
    always_comb begin
        if (is_active && i_req[current_ptr]) begin
            if (i_lock[current_ptr]) begin
                keep_current = 1'b1; // Lock overrides weight
            end else if (weight_cnt > 0) begin
                keep_current = 1'b1; // Normal weight credit
            end else begin
                keep_current = 1'b0; // Time's up
            end
        end else begin
            keep_current = 1'b0; // Not requesting or inactive
        end
    end

    // 2. Round Robin Search (Combinational Priority Encode)
    // Scans for the next requestor starting from (current_ptr + 1)
    always_comb begin
        found_next      = 1'b0;
        next_ptr_search = '0;
        next_gnt_search = '0;

        // Loop N times to check all clients in order: (ptr+1), (ptr+2)... (ptr)
        for (int i = 1; i <= NUM_CLIENTS; i++) begin
            // Calculate index safely without expensive modulo operator
            // Logic: (a + b) % N
            automatic int idx = int'(current_ptr) + i;
            if (idx >= NUM_CLIENTS) begin
                idx = idx - NUM_CLIENTS;
            end
            
            // Priority Check
            if (i_req[idx]) begin
                found_next           = 1'b1;
                next_ptr_search      = idx[$clog2(NUM_CLIENTS)-1:0];
                next_gnt_search[idx] = 1'b1;
                break; // Break on first found (Fixed Priority relative to ptr)
            end
        end
    end

    // -------------------------------------------------------------------------
    // Sequential State Update
    // -------------------------------------------------------------------------
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            current_gnt <= '0;
            // Initialize pointer to N-1 so the first search starts at 0
            current_ptr <= NUM_CLIENTS[$clog2(NUM_CLIENTS)-1:0] - 1'b1;
            weight_cnt  <= '0;
            is_active   <= 1'b0;
        end else begin
            if (keep_current) begin
                // --- Maintain Current Grant ---
                
                // Weight Logic:
                // Spec implies weight decrements even during lock, to determine
                // if we switch immediately upon unlock.
                if (weight_cnt > 0) begin
                    weight_cnt <= weight_cnt - 1'b1;
                end
                // If locked and weight_cnt is 0, it stays 0.
                
                // current_gnt stays the same
                // current_ptr stays the same
                // is_active stays 1

            end else begin
                // --- Rotate / Switch ---
                
                if (found_next) begin
                    // Grant to new owner
                    current_gnt <= next_gnt_search;
                    current_ptr <= next_ptr_search;
                    
                    // Load weight for the new owner
                    // Spec: Weight N means N+1 cycles. 
                    // Example: W=0 -> cnt=0. Cycle 1 checks 0>0 (False) -> Switch. Total 1.
                    weight_cnt  <= weight_array[next_ptr_search];
                    is_active   <= 1'b1;
                end else begin
                    // Go Idle
                    current_gnt <= '0;
                    is_active   <= 1'b0;
                    // Note: We keep current_ptr where it was, so next search 
                    // continues RR order from last owner.
                end
            end
        end
    end

    // -------------------------------------------------------------------------
    // Output Assignment
    // -------------------------------------------------------------------------
    assign o_gnt = current_gnt;

endmodule

`default_nettype wire