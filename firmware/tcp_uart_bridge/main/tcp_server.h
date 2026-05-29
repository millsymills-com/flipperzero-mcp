#pragma once

#include "esp_err.h"
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/**
 * TCP Server for TCP-UART Bridge
 *
 * Listens on configured port and manages client connections.
 * Data received from TCP is forwarded to UART, and vice versa.
 */

/**
 * Callback for data received from TCP client.
 *
 * @param data Pointer to received data
 * @param len Length of data
 */
typedef void (*tcp_rx_callback_t)(const uint8_t *data, size_t len);

/**
 * Initialize and start the TCP server.
 *
 * @param port Port to listen on
 * @param rx_callback Callback for received data
 * @return ESP_OK on success
 */
esp_err_t tcp_server_init(uint16_t port, tcp_rx_callback_t rx_callback);

/**
 * Send data to connected TCP client(s).
 *
 * @param data Pointer to data to send
 * @param len Length of data
 * @return Number of bytes sent, or -1 on error
 */
int tcp_server_send(const uint8_t *data, size_t len);

/**
 * Check if a client is connected.
 *
 * @return true if at least one client is connected
 */
bool tcp_server_has_client(void);

/**
 * Stop the TCP server and close all connections.
 */
void tcp_server_stop(void);
