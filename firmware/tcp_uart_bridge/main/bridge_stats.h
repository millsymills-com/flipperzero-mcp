/**
 * Bridge statistics (debug counters).
 *
 * These counters help debug the data path:
 * TCP client <-> ESP32 <-> Expansion Protocol <-> Flipper.
 *
 * Exposed via HTTP debug endpoint (/api/debug/counters).
 */
#pragma once

#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint32_t tcp_rx_bytes;
    uint32_t tcp_tx_bytes;
    uint32_t tcp_rx_packets;
    uint32_t tcp_tx_packets;
    uint32_t tcp_clients_accepted;
    uint32_t tcp_clients_closed;

    uint32_t exp_tx_frames;
    uint32_t exp_rx_frames;
    uint32_t exp_tx_data_bytes;
    uint32_t exp_rx_data_bytes;

    uint32_t exp_checksum_failures;
    uint32_t exp_unknown_frames;
    uint32_t exp_last_status;     /* last STATUS code received */
    uint32_t exp_last_frame_type; /* last frame type received */
} bridge_counters_t;

void bridge_stats_reset(void);
void bridge_stats_snapshot(bridge_counters_t *out);

void bridge_stats_inc_tcp_rx(size_t n);
void bridge_stats_inc_tcp_tx(size_t n);
void bridge_stats_inc_tcp_rx_packets(uint32_t n);
void bridge_stats_inc_tcp_tx_packets(uint32_t n);
void bridge_stats_inc_tcp_clients_accepted(uint32_t n);
void bridge_stats_inc_tcp_clients_closed(uint32_t n);

void bridge_stats_inc_exp_tx_frames(uint32_t n);
void bridge_stats_inc_exp_rx_frames(uint32_t n);
void bridge_stats_inc_exp_tx_data_bytes(size_t n);
void bridge_stats_inc_exp_rx_data_bytes(size_t n);
void bridge_stats_inc_exp_checksum_failures(uint32_t n);
void bridge_stats_inc_exp_unknown_frames(uint32_t n);
void bridge_stats_set_exp_last_status(uint32_t status);
void bridge_stats_set_exp_last_frame_type(uint32_t frame_type);
