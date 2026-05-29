#pragma once

#include "esp_err.h"
#include <stdbool.h>

/**
 * WiFi Manager for TCP-UART Bridge
 *
 * Manages WiFi connectivity with captive portal fallback:
 * - If stored credentials exist in NVS, connect to that network
 * - If connection fails or no credentials, start captive portal
 * - Captive portal allows user to configure SSID/password via web UI
 */

/**
 * Initialize the WiFi manager.
 * Attempts to connect using stored credentials, falls back to captive portal.
 *
 * @return ESP_OK on successful initialization
 */
esp_err_t wifi_manager_init(void);

/**
 * Check if WiFi is connected to an access point.
 *
 * @return true if connected to STA network
 */
bool wifi_manager_is_connected(void);

/**
 * Get the current IP address as a string.
 *
 * @param buf Buffer to store IP string (min 16 bytes)
 * @param buf_len Length of buffer
 * @return ESP_OK on success, ESP_ERR_INVALID_STATE if not connected
 */
esp_err_t wifi_manager_get_ip(char *buf, size_t buf_len);

/**
 * Clear stored WiFi credentials and restart captive portal.
 *
 * @return ESP_OK on success
 */
esp_err_t wifi_manager_reset_credentials(void);
