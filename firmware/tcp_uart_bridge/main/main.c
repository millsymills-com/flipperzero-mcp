/**
 * Flipper Zero WiFi Bridge with Expansion Module Protocol
 *
 * Connects to Flipper Zero via GPIO UART using the Expansion Module Protocol
 * to establish Protobuf RPC sessions over WiFi.
 *
 * Flow:
 *   HTTP/TCP Client <--WiFi--> ESP32 <--Expansion Protocol--> Flipper Zero
 *
 * Features:
 *   - Web-based captive portal for WiFi configuration
 *   - Expansion Module Protocol for Flipper communication
 *   - HTTP API for health/status/debug (no RPC translation yet)
 *   - LED status indication
 */

#include <stdio.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_system.h"
#include "driver/gpio.h"

#include "wifi_manager.h"
#include "tcp_server.h"
#include "expansion_module.h"
#include "http_api.h"
#include "sdkconfig.h"

static const char *TAG = "main";

/* LED pin for status indication */
#define STATUS_LED_PIN GPIO_NUM_15

/* UART pins for Flipper connection (configurable via menuconfig) */
#define FLIPPER_TX_PIN  CONFIG_BRIDGE_UART_TX_PIN  /* ESP32 TX -> Flipper RX (pin 14) */
#define FLIPPER_RX_PIN  CONFIG_BRIDGE_UART_RX_PIN  /* ESP32 RX <- Flipper TX (pin 13) */

/**
 * Callback: RPC data received from Flipper
 */
static void on_rpc_rx(const uint8_t *data, size_t len) {
    ESP_LOGI(TAG, "RPC RX: %d bytes", (int)len);

    /* Forward to TCP client if connected */
    tcp_server_send(data, len);

    /* TODO: Process RPC responses for HTTP API */
}

/**
 * Callback: data received from TCP client -> forward to Flipper RPC
 */
static void on_tcp_rx(const uint8_t *data, size_t len) {
    if (expansion_is_connected()) {
        expansion_send_rpc(data, len);
        ESP_LOGD(TAG, "TCP->RPC: %u bytes", (unsigned int)len);
    } else {
        ESP_LOGW(TAG, "TCP data received but Flipper not connected");
    }
}

/**
 * LED status task
 */
static void led_status_task(void *arg) {
    gpio_reset_pin(STATUS_LED_PIN);
    gpio_set_direction(STATUS_LED_PIN, GPIO_MODE_OUTPUT);

    while (1) {
        if (!wifi_manager_is_connected()) {
            /* Fast blink: not connected to WiFi */
            gpio_set_level(STATUS_LED_PIN, 1);
            vTaskDelay(pdMS_TO_TICKS(100));
            gpio_set_level(STATUS_LED_PIN, 0);
            vTaskDelay(pdMS_TO_TICKS(100));
        } else if (!expansion_is_connected()) {
            /* Medium blink: WiFi connected, Flipper not connected */
            gpio_set_level(STATUS_LED_PIN, 1);
            vTaskDelay(pdMS_TO_TICKS(300));
            gpio_set_level(STATUS_LED_PIN, 0);
            vTaskDelay(pdMS_TO_TICKS(300));
        } else if (!tcp_server_has_client()) {
            /* Slow blink: Flipper connected, no TCP client */
            gpio_set_level(STATUS_LED_PIN, 1);
            vTaskDelay(pdMS_TO_TICKS(500));
            gpio_set_level(STATUS_LED_PIN, 0);
            vTaskDelay(pdMS_TO_TICKS(500));
        } else {
            /* Solid on: fully connected */
            gpio_set_level(STATUS_LED_PIN, 1);
            vTaskDelay(pdMS_TO_TICKS(1000));
        }
    }
}

/**
 * Flipper connection task
 * Attempts to establish and maintain connection with Flipper
 */
static void flipper_connect_task(void *arg) {
    vTaskDelay(pdMS_TO_TICKS(1000));  /* Wait for system to stabilize */

    while (1) {
        expansion_state_t state = expansion_get_state();

        if (state == EXP_STATE_DISCONNECTED || state == EXP_STATE_ERROR) {
            ESP_LOGI(TAG, "Attempting to connect to Flipper...");
            expansion_connect();

            /* Wait for connection attempt to complete */
            for (int i = 0; i < 20; i++) {  /* 2 second timeout */
                vTaskDelay(pdMS_TO_TICKS(100));
                state = expansion_get_state();
                if (state == EXP_STATE_RPC_ACTIVE) {
                    ESP_LOGI(TAG, "*** Connected to Flipper! RPC session active ***");
                    break;
                } else if (state == EXP_STATE_ERROR) {
                    ESP_LOGW(TAG, "Connection failed, will retry...");
                    break;
                }
            }

            if (state != EXP_STATE_RPC_ACTIVE) {
                /* Connection timed out or failed, wait before retry */
                expansion_disconnect();
                vTaskDelay(pdMS_TO_TICKS(3000));
            }
        } else if (state == EXP_STATE_RPC_ACTIVE) {
            /* Connected, just monitor */
            vTaskDelay(pdMS_TO_TICKS(1000));
        } else {
            /* In progress, wait */
            vTaskDelay(pdMS_TO_TICKS(100));
        }
    }
}

void app_main(void) {
    ESP_LOGI(TAG, "==========================================");
    ESP_LOGI(TAG, "Flipper Zero WiFi Bridge (Expansion Mode)");
    ESP_LOGI(TAG, "==========================================");
    ESP_LOGI(TAG, "UART: TX=%d -> Flipper RX, RX=%d <- Flipper TX",
             FLIPPER_TX_PIN, FLIPPER_RX_PIN);

    /* Start LED status task */
    xTaskCreate(led_status_task, "led_status", 2048, NULL, 1, NULL);

    /* Initialize WiFi manager */
    ESP_LOGI(TAG, "Initializing WiFi...");
    esp_err_t err = wifi_manager_init();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "WiFi init failed: %s", esp_err_to_name(err));
        return;
    }

    /* Wait for WiFi connection */
    ESP_LOGI(TAG, "Waiting for WiFi connection...");
    while (!wifi_manager_is_connected()) {
        vTaskDelay(pdMS_TO_TICKS(1000));
    }

    char ip_str[16];
    wifi_manager_get_ip(ip_str, sizeof(ip_str));
    ESP_LOGI(TAG, "WiFi connected! IP: %s", ip_str);

    /* Initialize Expansion Module protocol */
    ESP_LOGI(TAG, "Initializing Flipper Expansion Module...");
    err = expansion_init(FLIPPER_TX_PIN, FLIPPER_RX_PIN, on_rpc_rx);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Expansion init failed: %s", esp_err_to_name(err));
        return;
    }

    /* Initialize TCP server (for raw Protobuf RPC forwarding) */
    ESP_LOGI(TAG, "Starting TCP server on port %d...", CONFIG_BRIDGE_TCP_PORT);
    err = tcp_server_init(CONFIG_BRIDGE_TCP_PORT, on_tcp_rx);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "TCP server init failed: %s", esp_err_to_name(err));
        return;
    }

    /* Initialize HTTP API server */
    ESP_LOGI(TAG, "Starting HTTP API on port 80...");
    err = http_api_init(80);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "HTTP API init failed: %s", esp_err_to_name(err));
        return;
    }

    ESP_LOGI(TAG, "==========================================");
    ESP_LOGI(TAG, "Bridge ready!");
    ESP_LOGI(TAG, "HTTP: http://%s/api/health", ip_str);
    ESP_LOGI(TAG, "TCP:  %s:%d (Protobuf RPC)", ip_str, CONFIG_BRIDGE_TCP_PORT);
    ESP_LOGI(TAG, "==========================================");
    ESP_LOGI(TAG, "Make sure Flipper has Expansion Modules enabled!");
    ESP_LOGI(TAG, "  Settings -> Expansion Modules -> USART");
    ESP_LOGI(TAG, "==========================================");

    /* Start Flipper connection task */
    xTaskCreate(flipper_connect_task, "flipper_conn", 4096, NULL, 5, NULL);

    /* Main loop - just keep running */
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(10000));

        if (!wifi_manager_is_connected()) {
            ESP_LOGW(TAG, "WiFi connection lost...");
        }

        if (expansion_is_connected()) {
            ESP_LOGI(TAG, "Status: Flipper connected, RPC active");
        } else {
            ESP_LOGI(TAG, "Status: Flipper not connected (state=%d)",
                     expansion_get_state());
        }
    }
}
