/**
 * Flipper Zero Expansion Module Protocol
 *
 * Implements the serial protocol for ESP32 to act as an expansion module
 * and establish Protobuf RPC sessions with Flipper Zero over GPIO UART.
 *
 * Protocol: https://developer.flipper.net/flipperzero/doxygen/expansion_protocol.html
 */

#pragma once

#include "esp_err.h"
#include "sdkconfig.h"
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

/* Frame types */
#define EXP_FRAME_HEARTBEAT   0x01
#define EXP_FRAME_STATUS      0x02
#define EXP_FRAME_BAUD_RATE   0x03
#define EXP_FRAME_CONTROL     0x04
#define EXP_FRAME_DATA        0x05

/* Status/Error codes */
#define EXP_STATUS_OK                 0x00
#define EXP_STATUS_ERROR_UNKNOWN      0x01
#define EXP_STATUS_ERROR_BAUD_RATE    0x02

/* Control commands */
#define EXP_CONTROL_START_RPC   0x00
#define EXP_CONTROL_STOP_RPC    0x01
#define EXP_CONTROL_ENABLE_OTG  0x02
#define EXP_CONTROL_DISABLE_OTG 0x03

/* Protocol timing (ms) */
#define EXP_TIMEOUT_MS          250
#define EXP_BAUD_SWITCH_DEAD_MS 25
#define EXP_INITIAL_BAUD        9600
/* Target baud rate after negotiation (configurable via menuconfig). */
#define EXP_TARGET_BAUD         CONFIG_BRIDGE_UART_BAUD_RATE

/* Data frame limits */
#define EXP_DATA_MAX_PAYLOAD    64

/* Connection state */
typedef enum {
    EXP_STATE_DISCONNECTED,
    EXP_STATE_AWAITING_HEARTBEAT,
    EXP_STATE_BAUD_NEGOTIATION,
    EXP_STATE_RPC_STARTING,
    EXP_STATE_RPC_ACTIVE,
    EXP_STATE_ERROR
} expansion_state_t;

/* Callback for received RPC data */
typedef void (*expansion_rpc_rx_callback_t)(const uint8_t *data, size_t len);

/**
 * Initialize expansion module protocol handler.
 *
 * @param tx_pin GPIO pin for UART TX
 * @param rx_pin GPIO pin for UART RX
 * @param rpc_callback Callback for received RPC data from Flipper
 * @return ESP_OK on success
 */
esp_err_t expansion_init(int tx_pin, int rx_pin, expansion_rpc_rx_callback_t rpc_callback);

/**
 * Start connection to Flipper Zero.
 * Initiates handshake sequence.
 *
 * @return ESP_OK if handshake started
 */
esp_err_t expansion_connect(void);

/**
 * Send RPC data to Flipper Zero.
 * Must be in RPC_ACTIVE state.
 *
 * @param data Protobuf RPC data
 * @param len Data length (max 64 bytes per frame)
 * @return ESP_OK on success
 */
esp_err_t expansion_send_rpc(const uint8_t *data, size_t len);

/**
 * Process incoming UART data.
 * Call this from UART RX handler.
 *
 * @param data Received bytes
 * @param len Number of bytes
 */
void expansion_uart_rx(const uint8_t *data, size_t len);

/**
 * Get current connection state.
 */
expansion_state_t expansion_get_state(void);

/**
 * Check if RPC session is active.
 */
bool expansion_is_connected(void);

/**
 * Disconnect and reset to initial state.
 */
void expansion_disconnect(void);

/**
 * Send heartbeat to maintain connection.
 * Call periodically (< 250ms) when idle.
 */
esp_err_t expansion_send_heartbeat(void);
