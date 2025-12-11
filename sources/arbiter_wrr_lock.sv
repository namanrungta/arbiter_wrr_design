`default_nettype none`

module arbiter_wrr_lock #(
    parameter int NUM_CLIENTS  = 4,
    parameter int WEIGHT_WIDTH = 4
) (
    input  wire                               clk,
    input  wire                               rst_n,

    input  wire [NUM_CLIENTS-1:0]             i_req,
    input  wire [NUM_CLIENTS-1:0]             i_lock,    // Unused in baseline
    input  wire [NUM_CLIENTS*WEIGHT_WIDTH-1:0] i_weight, // Unused in baseline

    output logic [NUM_CLIENTS-1:0]            o_gnt
);

    // Simple priority grant (client 0 highest). Ignores weights/locks and does
    // not rotate, so it fails fairness and lock requirements from the spec.
    logic [NUM_CLIENTS-1:0] grant_next;

    always_comb begin
        grant_next = '0;
        for (int i = 0; i < NUM_CLIENTS; i++) begin
            if (i_req[i]) begin
                grant_next[i] = 1'b1;
                break;
            end
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            o_gnt <= '0;
        end else begin
            o_gnt <= grant_next;
        end
    end

endmodule

`default_nettype wire