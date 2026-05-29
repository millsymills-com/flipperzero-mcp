#pragma once

#include "esp_err.h"
#include "esp_http_server.h"

/**
 * HTTP API for Flipper WiFi Bridge
 *
 * Provides bridge status endpoints. RPC translation endpoints are placeholders.
 *
 * Endpoints:
 *   GET  /api/health              - Bridge health check
 *   GET  /api/status              - Detailed bridge status
 *
 * NOTE:
 * This firmware currently exposes raw Protobuf RPC over TCP (default 8080).
 * The HTTP endpoints for translating requests into Protobuf RPC are not yet implemented.
 */

/**
 * Initialize and start the HTTP API server.
 *
 * @param port Port to listen on (e.g., 80)
 * @return ESP_OK on success
 */
esp_err_t http_api_init(uint16_t port);

/**
 * Stop the HTTP API server.
 */
void http_api_stop(void);

/**
 * Check if HTTP API server is running.
 *
 * @return true if running
 */
bool http_api_is_running(void);

/**
 * Feed UART data to HTTP API for CLI response processing.
 * Call this from UART RX callback.
 *
 * @param data Received bytes
 * @param len Number of bytes
 */
void http_api_uart_rx(const uint8_t *data, size_t len);
