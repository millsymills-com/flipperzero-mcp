/**
 * Bridge statistics (debug counters).
 */

#include "bridge_stats.h"

#include <string.h>
#include <stdatomic.h>

static atomic_uint_fast32_t s_tcp_rx_bytes;
static atomic_uint_fast32_t s_tcp_tx_bytes;
static atomic_uint_fast32_t s_tcp_rx_packets;
static atomic_uint_fast32_t s_tcp_tx_packets;
static atomic_uint_fast32_t s_tcp_clients_accepted;
static atomic_uint_fast32_t s_tcp_clients_closed;

static atomic_uint_fast32_t s_exp_tx_frames;
static atomic_uint_fast32_t s_exp_rx_frames;
static atomic_uint_fast32_t s_exp_tx_data_bytes;
static atomic_uint_fast32_t s_exp_rx_data_bytes;
static atomic_uint_fast32_t s_exp_checksum_failures;
static atomic_uint_fast32_t s_exp_unknown_frames;
static atomic_uint_fast32_t s_exp_last_status;
static atomic_uint_fast32_t s_exp_last_frame_type;

void bridge_stats_reset(void) {
    atomic_store(&s_tcp_rx_bytes, 0);
    atomic_store(&s_tcp_tx_bytes, 0);
    atomic_store(&s_tcp_rx_packets, 0);
    atomic_store(&s_tcp_tx_packets, 0);
    atomic_store(&s_tcp_clients_accepted, 0);
    atomic_store(&s_tcp_clients_closed, 0);

    atomic_store(&s_exp_tx_frames, 0);
    atomic_store(&s_exp_rx_frames, 0);
    atomic_store(&s_exp_tx_data_bytes, 0);
    atomic_store(&s_exp_rx_data_bytes, 0);
    atomic_store(&s_exp_checksum_failures, 0);
    atomic_store(&s_exp_unknown_frames, 0);
    atomic_store(&s_exp_last_status, 0);
    atomic_store(&s_exp_last_frame_type, 0);
}

void bridge_stats_snapshot(bridge_counters_t *out) {
    if (!out) return;
    memset(out, 0, sizeof(*out));
    out->tcp_rx_bytes = (uint32_t)atomic_load(&s_tcp_rx_bytes);
    out->tcp_tx_bytes = (uint32_t)atomic_load(&s_tcp_tx_bytes);
    out->tcp_rx_packets = (uint32_t)atomic_load(&s_tcp_rx_packets);
    out->tcp_tx_packets = (uint32_t)atomic_load(&s_tcp_tx_packets);
    out->tcp_clients_accepted = (uint32_t)atomic_load(&s_tcp_clients_accepted);
    out->tcp_clients_closed = (uint32_t)atomic_load(&s_tcp_clients_closed);

    out->exp_tx_frames = (uint32_t)atomic_load(&s_exp_tx_frames);
    out->exp_rx_frames = (uint32_t)atomic_load(&s_exp_rx_frames);
    out->exp_tx_data_bytes = (uint32_t)atomic_load(&s_exp_tx_data_bytes);
    out->exp_rx_data_bytes = (uint32_t)atomic_load(&s_exp_rx_data_bytes);
    out->exp_checksum_failures = (uint32_t)atomic_load(&s_exp_checksum_failures);
    out->exp_unknown_frames = (uint32_t)atomic_load(&s_exp_unknown_frames);
    out->exp_last_status = (uint32_t)atomic_load(&s_exp_last_status);
    out->exp_last_frame_type = (uint32_t)atomic_load(&s_exp_last_frame_type);
}

void bridge_stats_inc_tcp_rx(size_t n) { atomic_fetch_add(&s_tcp_rx_bytes, (uint32_t)n); }
void bridge_stats_inc_tcp_tx(size_t n) { atomic_fetch_add(&s_tcp_tx_bytes, (uint32_t)n); }
void bridge_stats_inc_tcp_rx_packets(uint32_t n) { atomic_fetch_add(&s_tcp_rx_packets, n); }
void bridge_stats_inc_tcp_tx_packets(uint32_t n) { atomic_fetch_add(&s_tcp_tx_packets, n); }
void bridge_stats_inc_tcp_clients_accepted(uint32_t n) { atomic_fetch_add(&s_tcp_clients_accepted, n); }
void bridge_stats_inc_tcp_clients_closed(uint32_t n) { atomic_fetch_add(&s_tcp_clients_closed, n); }

void bridge_stats_inc_exp_tx_frames(uint32_t n) { atomic_fetch_add(&s_exp_tx_frames, n); }
void bridge_stats_inc_exp_rx_frames(uint32_t n) { atomic_fetch_add(&s_exp_rx_frames, n); }
void bridge_stats_inc_exp_tx_data_bytes(size_t n) { atomic_fetch_add(&s_exp_tx_data_bytes, (uint32_t)n); }
void bridge_stats_inc_exp_rx_data_bytes(size_t n) { atomic_fetch_add(&s_exp_rx_data_bytes, (uint32_t)n); }
void bridge_stats_inc_exp_checksum_failures(uint32_t n) { atomic_fetch_add(&s_exp_checksum_failures, n); }
void bridge_stats_inc_exp_unknown_frames(uint32_t n) { atomic_fetch_add(&s_exp_unknown_frames, n); }
void bridge_stats_set_exp_last_status(uint32_t status) { atomic_store(&s_exp_last_status, status); }
void bridge_stats_set_exp_last_frame_type(uint32_t frame_type) { atomic_store(&s_exp_last_frame_type, frame_type); }
