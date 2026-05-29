#pragma once

#include "esp_err.h"
#include <stddef.h>
#include <stdint.h>

/**
 * UART Bridge for TCP-UART Bridge
 *
 * Handles UART communication with Flipper Zero.
 * Data received from UART is forwarded to the registered callback.
 */

/**
 * Callback for data received from UART.
 *
 * @param data Pointer to received data
 * @param len Length of data
 */
typedef void (*uart_rx_callback_t)(const uint8_t *data, size_t len);

/**
 * Initialize the UART bridge.
 *
 * @param tx_pin GPIO pin for TX
 * @param rx_pin GPIO pin for RX
 * @param baud_rate UART baud rate
 * @param rx_callback Callback for received data
 * @return ESP_OK on success
 */
esp_err_t uart_bridge_init(int tx_pin, int rx_pin, int baud_rate,
                           uart_rx_callback_t rx_callback);

/**
 * Send data over UART.
 *
 * @param data Pointer to data to send
 * @param len Length of data
 * @return Number of bytes sent, or -1 on error
 */
int uart_bridge_send(const uint8_t *data, size_t len);

/**
 * Stop the UART bridge and release resources.
 */
void uart_bridge_stop(void);
