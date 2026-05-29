/**
 * UART Bridge Implementation
 *
 * Handles UART communication with Flipper Zero.
 */

#include "uart_bridge.h"

#include <string.h>

#include "driver/uart.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"

static const char *TAG = "uart_bridge";

#define UART_NUM UART_NUM_1
#define UART_BUF_SIZE 2048
#define RX_TASK_STACK_SIZE 4096

/* State */
static uart_rx_callback_t s_rx_callback = NULL;
static TaskHandle_t s_rx_task = NULL;
static volatile bool s_running = false;
static QueueHandle_t s_uart_queue = NULL;

/* Forward declarations */
static void uart_rx_task(void *arg);

esp_err_t uart_bridge_init(int tx_pin, int rx_pin, int baud_rate,
                           uart_rx_callback_t rx_callback) {
    if (s_running) {
        ESP_LOGW(TAG, "UART bridge already running");
        return ESP_ERR_INVALID_STATE;
    }

    s_rx_callback = rx_callback;

    /* UART configuration */
    uart_config_t uart_config = {
        .baud_rate = baud_rate,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };

    esp_err_t err;

    /* Install UART driver */
    err = uart_driver_install(UART_NUM, UART_BUF_SIZE * 2, UART_BUF_SIZE * 2,
                              20, &s_uart_queue, 0);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Failed to install UART driver: %s", esp_err_to_name(err));
        return err;
    }

    /* Configure UART parameters */
    err = uart_param_config(UART_NUM, &uart_config);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Failed to configure UART: %s", esp_err_to_name(err));
        uart_driver_delete(UART_NUM);
        return err;
    }

    /* Set UART pins */
    err = uart_set_pin(UART_NUM, tx_pin, rx_pin, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Failed to set UART pins: %s", esp_err_to_name(err));
        uart_driver_delete(UART_NUM);
        return err;
    }

    s_running = true;

    /* Start RX task */
    xTaskCreate(uart_rx_task, "uart_rx", RX_TASK_STACK_SIZE, NULL, 7, &s_rx_task);

    ESP_LOGI(TAG, "UART bridge initialized (TX=%d, RX=%d, baud=%d)", tx_pin, rx_pin, baud_rate);
    return ESP_OK;
}

static void uart_rx_task(void *arg) {
    uint8_t *rx_buffer = (uint8_t *)malloc(UART_BUF_SIZE);
    if (rx_buffer == NULL) {
        ESP_LOGE(TAG, "Failed to allocate RX buffer");
        vTaskDelete(NULL);
        return;
    }

    ESP_LOGI(TAG, "UART RX task started");

    while (s_running) {
        /* Read data from UART */
        int len = uart_read_bytes(UART_NUM, rx_buffer, UART_BUF_SIZE, pdMS_TO_TICKS(100));

        if (len > 0) {
            ESP_LOGD(TAG, "Received %d bytes from UART", len);

            /* Forward to callback */
            if (s_rx_callback) {
                s_rx_callback(rx_buffer, len);
            }
        } else if (len < 0) {
            ESP_LOGE(TAG, "UART read error");
            vTaskDelay(pdMS_TO_TICKS(100));
        }
    }

    free(rx_buffer);
    ESP_LOGI(TAG, "UART RX task exiting");
    vTaskDelete(NULL);
}

int uart_bridge_send(const uint8_t *data, size_t len) {
    if (!s_running || data == NULL || len == 0) {
        return -1;
    }

    int written = uart_write_bytes(UART_NUM, data, len);

    if (written < 0) {
        ESP_LOGE(TAG, "UART write failed");
        return -1;
    }

    ESP_LOGD(TAG, "Sent %d bytes to UART", written);
    return written;
}

void uart_bridge_stop(void) {
    if (!s_running) return;

    ESP_LOGI(TAG, "Stopping UART bridge");
    s_running = false;

    /* Wait for task to exit */
    vTaskDelay(pdMS_TO_TICKS(200));

    /* Delete UART driver */
    uart_driver_delete(UART_NUM);

    s_rx_task = NULL;
    s_uart_queue = NULL;

    ESP_LOGI(TAG, "UART bridge stopped");
}
