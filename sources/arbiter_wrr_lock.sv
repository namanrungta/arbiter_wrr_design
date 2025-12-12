`timescale 1ns/1ps

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
    
    // Use Packed Array for weight storage
    logic [NUM_CLIENTS-1:0][WEIGHT_WIDTH-1:0] weight_packed;
    
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
    
    // Combinational Weight Mux
    logic [WEIGHT_WIDTH-1:0]         next_weight_val;

    // -------------------------------------------------------------------------
    // Weight Alias
    // -------------------------------------------------------------------------
    assign weight_packed = i_weight;

    // -------------------------------------------------------------------------
    // Arbitration Logic
    // -------------------------------------------------------------------------

    // 1. Check if the Current Owner keeps the grant
    always_comb begin
        if (is_active && i_req[current_ptr]) begin
            // Check Lock (Spec 3.3): Only valid if held by current owner
            if (i_lock[current_ptr]) begin
                keep_current = 1'b1;
            end 
            // Check Weight Credits (Spec 3.2)
            else if (weight_cnt > 0) begin
                keep_current = 1'b1;
            end 
            else begin
                keep_current = 1'b0; // Time's up
            end
        end else begin
            keep_current = 1'b0; // Dropped request or inactive
        end
    end

    // 2. Round Robin Search (Forward Loop with Flag)
    // We scan from CLOSEST (current_ptr + 1) to FURTHEST.
    // We capture the FIRST match using the 'already_found' flag logic.
    // This avoids 'break' while ensuring strict priority.
    always_comb begin
        logic already_found; 
        
        found_next      = 1'b0;
        next_ptr_search = '0;
        next_gnt_search = '0;
        already_found   = 1'b0;
        
        for (int i = 1; i <= NUM_CLIENTS; i++) begin
            // Calculate candidate index with manual wrap-around
            int idx;
            idx = int'(current_ptr) + i;
            if (idx >= NUM_CLIENTS) begin
                idx = idx - NUM_CLIENTS;
            end
            
            // If request exists AND we haven't found a closer one yet
            if (i_req[idx] && !already_found) begin
                found_next           = 1'b1;
                next_ptr_search      = idx[$clog2(NUM_CLIENTS)-1:0];
                
                next_gnt_search      = '0;
                next_gnt_search[idx] = 1'b1;
                
                already_found        = 1'b1; // Lock the decision
            end
        end
    end
    
    // 3. Weight Mux (Resolves "Constant Selects" error in Icarus)
    // Extract the weight for the *next* winner combinationally
    always_comb begin
        next_weight_val = weight_packed[next_ptr_search];
    end

    // -------------------------------------------------------------------------
    // Sequential State Update
    // -------------------------------------------------------------------------
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            current_gnt <= '0;
            // Initialize to N-1 so the first search (ptr+1) checks Client 0 first.
            current_ptr <= NUM_CLIENTS[$clog2(NUM_CLIENTS)-1:0] - 1'b1;
            weight_cnt  <= '0;
            is_active   <= 1'b0;
        end else begin
            if (keep_current) begin
                // --- Maintain Current Grant ---
                // Decrement weight if > 0
                if (weight_cnt > 0) begin
                    weight_cnt <= weight_cnt - 1'b1;
                end
            end else begin
                // --- Rotate / Switch ---
                if (found_next) begin
                    current_gnt <= next_gnt_search;
                    current_ptr <= next_ptr_search;
                    
                    // Load extracted weight
                    weight_cnt  <= next_weight_val;
                    is_active   <= 1'b1;
                end else begin
                    // No requests: Go Idle
                    current_gnt <= '0;
                    is_active   <= 1'b0;
                end
            end
        end
    end

    assign o_gnt = current_gnt;
endmodule