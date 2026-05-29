/**
 * Flipper Zero Expansion Module Protocol Implementation
 */

#include "expansion_module.h"

#include <string.h>
#include "sdkconfig.h"
#include "esp_log.h"
#include "driver/uart.h"
#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "freertos/queue.h"

#include "bridge_stats.h"

static const char *TAG = "expansion";

#define UART_NUM        UART_NUM_1
#define UART_BUF_SIZE   256
#define RX_BUF_SIZE     256

/* State */
static expansion_state_t s_state = EXP_STATE_DISCONNECTED;
static expansion_rpc_rx_callback_t s_rpc_callback = NULL;
static int s_tx_pin = -1;
static int s_rx_pin = -1;
static uint32_t s_current_baud = EXP_INITIAL_BAUD;
static SemaphoreHandle_t s_mutex = NULL;
static TaskHandle_t s_rx_task = NULL;

/* RX buffer for frame assembly */
static uint8_t s_rx_buf[RX_BUF_SIZE];
static size_t s_rx_len = 0;

/* Watchdog: last time we received any valid bytes/frame from Flipper */
static TickType_t s_last_rx_tick = 0;

/* Calculate XOR checksum */
static uint8_t calc_checksum(const uint8_t *data, size_t len) {
    uint8_t checksum = 0;
    for (size_t i = 0; i < len; i++) {
        checksum ^= data[i];
    }
    return checksum;
}

/* Send raw frame with checksum */
static esp_err_t send_frame(const uint8_t *frame, size_t len) {
    uint8_t checksum = calc_checksum(frame, len);

    int sent = uart_write_bytes(UART_NUM, (const char *)frame, len);
    if (sent != len) return ESP_FAIL;

    sent = uart_write_bytes(UART_NUM, (const char *)&checksum, 1);
    if (sent != 1) return ESP_FAIL;

    uart_wait_tx_done(UART_NUM, pdMS_TO_TICKS(100));

    ESP_LOGD(TAG, "TX frame type=0x%02x len=%d", frame[0], (int)len);
    bridge_stats_inc_exp_tx_frames(1);
    return ESP_OK;
}

/* Send HEARTBEAT frame */
esp_err_t expansion_send_heartbeat(void) {
    uint8_t frame[] = { EXP_FRAME_HEARTBEAT };
    return send_frame(frame, sizeof(frame));
}

/* Send STATUS frame */
static esp_err_t send_status(uint8_t status_code) {
    uint8_t frame[] = { EXP_FRAME_STATUS, status_code };
    return send_frame(frame, sizeof(frame));
}

/* Send BAUD_RATE frame */
static esp_err_t send_baud_rate(uint32_t baud) {
    uint8_t frame[5];
    frame[0] = EXP_FRAME_BAUD_RATE;
    frame[1] = (baud >> 0) & 0xFF;
    frame[2] = (baud >> 8) & 0xFF;
    frame[3] = (baud >> 16) & 0xFF;
    frame[4] = (baud >> 24) & 0xFF;
    return send_frame(frame, sizeof(frame));
}

/* Send CONTROL frame */
static esp_err_t send_control(uint8_t command) {
    uint8_t frame[] = { EXP_FRAME_CONTROL, command };
    return send_frame(frame, sizeof(frame));
}

/* Send DATA frame (RPC payload) */
static esp_err_t send_data_frame(const uint8_t *data, size_t len) {
    if (len > EXP_DATA_MAX_PAYLOAD) {
        return ESP_ERR_INVALID_SIZE;
    }

    uint8_t frame[2 + EXP_DATA_MAX_PAYLOAD];
    frame[0] = EXP_FRAME_DATA;
    frame[1] = (uint8_t)len;
    if (len) memcpy(&frame[2], data, len);

    /*
     * On-wire framing for DATA uses a length byte followed by that many payload bytes
     * (up to EXP_DATA_MAX_PAYLOAD). The struct in docs defines the maximum size, but
     * frames are transmitted in their minimal form: type + size + payload + checksum.
     */
    return send_frame(frame, 2 + len);
}

/* Change UART baud rate */
static esp_err_t set_baud_rate(uint32_t baud) {
    esp_err_t err = uart_set_baudrate(UART_NUM, baud);
    if (err == ESP_OK) {
        s_current_baud = baud;
        ESP_LOGI(TAG, "Baud rate changed to %lu", (unsigned long)baud);
    }
    return err;
}

/* Pull TX pin low to signal presence to Flipper (pulls Flipper's RX low) */
static void signal_presence(void) {
    /*
     * IMPORTANT:
     * We must not tear down/reinstall the UART driver while the RX task is
     * executing uart_read_bytes(). That can lead to undefined behavior.
     *
     * We suspend the RX task briefly, uninstall the driver, pulse TX low,
     * then re-install and resume. This keeps the driver/task lifecycle coherent.
     */
    if (s_mutex) {
        xSemaphoreTake(s_mutex, portMAX_DELAY);
    }

    if (s_rx_task) {
        vTaskSuspend(s_rx_task);
    }

    /* Best-effort wait for TX FIFO to drain before we reconfigure pins. */
    (void)uart_wait_tx_done(UART_NUM, pdMS_TO_TICKS(50));

    /* Temporarily reconfigure TX as GPIO output, pulse low, then restore UART. */
    (void)uart_driver_delete(UART_NUM);

    gpio_reset_pin(s_tx_pin);
    gpio_set_direction(s_tx_pin, GPIO_MODE_OUTPUT);
    gpio_set_level(s_tx_pin, 0);
    vTaskDelay(pdMS_TO_TICKS(2));  /* Brief low pulse */
    gpio_set_level(s_tx_pin, 1);
    gpio_reset_pin(s_tx_pin);

    /* Reinitialize UART */
    uart_config_t uart_config = {
        .baud_rate = s_current_baud,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };

    (void)uart_driver_install(UART_NUM, UART_BUF_SIZE * 2, 0, 0, NULL, 0);
    (void)uart_param_config(UART_NUM, &uart_config);
    (void)uart_set_pin(UART_NUM, s_tx_pin, s_rx_pin, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);

    if (s_rx_task) {
        vTaskResume(s_rx_task);
    }

    if (s_mutex) {
        xSemaphoreGive(s_mutex);
    }

    ESP_LOGI(TAG, "Signaled presence to Flipper (safe)");
}

/* Get expected frame size based on type and content */
static int get_frame_size(uint8_t frame_type, const uint8_t *data, size_t available) {
    switch (frame_type) {
        case EXP_FRAME_HEARTBEAT:
            return 2;  /* type + checksum */
        case EXP_FRAME_STATUS:
            return 3;  /* type + status + checksum */
        case EXP_FRAME_BAUD_RATE:
            return 6;  /* type + 4 bytes baud + checksum */
        case EXP_FRAME_CONTROL:
            return 3;  /* type + command + checksum */
        case EXP_FRAME_DATA:
            if (available >= 2) {
                /* type + size + payload(size) + checksum */
                uint8_t payload_len = data[1];
                if (payload_len > EXP_DATA_MAX_PAYLOAD) {
                    return -2; /* Invalid length */
                }
                return 2 + payload_len + 1;
            }
            return -1;  /* Need more data */
        default:
            return -2;  /* Unknown frame */
    }
}

/* Process a complete frame */
static void process_frame(const uint8_t *frame, size_t len) {
    if (len < 2) return;

    s_last_rx_tick = xTaskGetTickCount();
    bridge_stats_inc_exp_rx_frames(1);
    bridge_stats_set_exp_last_frame_type(frame[0]);

    /* Verify checksum */
    uint8_t expected = calc_checksum(frame, len - 1);
    uint8_t received = frame[len - 1];
    if (expected != received) {
        ESP_LOGW(TAG, "Checksum mismatch: expected 0x%02x, got 0x%02x", expected, received);
        bridge_stats_inc_exp_checksum_failures(1);
        s_state = EXP_STATE_ERROR;
        return;
    }

    uint8_t frame_type = frame[0];
    ESP_LOGD(TAG, "RX frame type=0x%02x state=%d", frame_type, s_state);

    switch (s_state) {
        case EXP_STATE_AWAITING_HEARTBEAT:
            if (frame_type == EXP_FRAME_HEARTBEAT) {
                ESP_LOGI(TAG, "Got HEARTBEAT, sending baud rate request");
                s_state = EXP_STATE_BAUD_NEGOTIATION;
                /* Request target baud rate */
                send_baud_rate(EXP_TARGET_BAUD);
            }
            break;

        case EXP_STATE_BAUD_NEGOTIATION:
            if (frame_type == EXP_FRAME_STATUS) {
                uint8_t status = frame[1];
                bridge_stats_set_exp_last_status(status);
                if (status == EXP_STATUS_OK) {
                    ESP_LOGI(TAG, "Baud rate accepted, switching");
                    vTaskDelay(pdMS_TO_TICKS(EXP_BAUD_SWITCH_DEAD_MS));
                    set_baud_rate(EXP_TARGET_BAUD);
                    vTaskDelay(pdMS_TO_TICKS(EXP_BAUD_SWITCH_DEAD_MS));

                    /* Start RPC session */
                    s_state = EXP_STATE_RPC_STARTING;
                    send_control(EXP_CONTROL_START_RPC);
                } else if (status == EXP_STATUS_ERROR_BAUD_RATE) {
                    ESP_LOGW(TAG, "Baud rate rejected, staying at 9600");
                    /* Stay at initial baud, try to start RPC anyway */
                    s_state = EXP_STATE_RPC_STARTING;
                    send_control(EXP_CONTROL_START_RPC);
                } else {
                    ESP_LOGE(TAG, "Baud negotiation error: 0x%02x", status);
                    s_state = EXP_STATE_ERROR;
                }
            }
            break;

        case EXP_STATE_RPC_STARTING:
            if (frame_type == EXP_FRAME_STATUS) {
                uint8_t status = frame[1];
                bridge_stats_set_exp_last_status(status);
                if (status == EXP_STATUS_OK) {
                    ESP_LOGI(TAG, "RPC session started!");
                    s_state = EXP_STATE_RPC_ACTIVE;
                } else {
                    ESP_LOGE(TAG, "RPC start failed: 0x%02x", status);
                    s_state = EXP_STATE_ERROR;
                }
            }
            break;

        case EXP_STATE_RPC_ACTIVE:
            if (frame_type == EXP_FRAME_DATA) {
                /* Extract RPC payload */
                uint8_t payload_len = frame[1];
                if (payload_len > 0 && s_rpc_callback) {
                    bridge_stats_inc_exp_rx_data_bytes(payload_len);
                    s_rpc_callback(&frame[2], payload_len);
                }
                /* ACK with STATUS OK */
                send_status(EXP_STATUS_OK);
            } else if (frame_type == EXP_FRAME_STATUS) {
                /* ACK for our sent data, ignore */
                bridge_stats_set_exp_last_status(frame[1]);
            } else if (frame_type == EXP_FRAME_HEARTBEAT) {
                /* Respond to heartbeat to maintain connection */
                expansion_send_heartbeat();
            } else {
                bridge_stats_inc_exp_unknown_frames(1);
            }
            break;

        default:
            break;
    }
}

/* UART RX task */
static void uart_rx_task(void *arg) {
    uint8_t buf[128];

    while (1) {
        int len = uart_read_bytes(UART_NUM, buf, sizeof(buf), pdMS_TO_TICKS(50));
        if (len > 0) {
            ESP_LOGD(TAG, "UART RX: %d bytes", len);

            /* Add to buffer */
            size_t to_copy = len;
            if (s_rx_len + to_copy > RX_BUF_SIZE) {
                to_copy = RX_BUF_SIZE - s_rx_len;
            }
            memcpy(s_rx_buf + s_rx_len, buf, to_copy);
            s_rx_len += to_copy;

            /* Try to extract complete frames */
            while (s_rx_len > 0) {
                int frame_size = get_frame_size(s_rx_buf[0], s_rx_buf, s_rx_len);

                if (frame_size == -1) {
                    /* Need more data */
                    break;
                } else if (frame_size == -2) {
                    /* Unknown frame type, skip byte */
                    ESP_LOGW(TAG, "Unknown frame type: 0x%02x", s_rx_buf[0]);
                    memmove(s_rx_buf, s_rx_buf + 1, --s_rx_len);
                } else if ((size_t)frame_size <= s_rx_len) {
                    /* Complete frame available */
                    process_frame(s_rx_buf, frame_size);
                    memmove(s_rx_buf, s_rx_buf + frame_size, s_rx_len - frame_size);
                    s_rx_len -= frame_size;
                } else {
                    /* Need more data */
                    break;
                }
            }
        }

        /* RX watchdog: if we stop receiving frames for too long, force a reconnect. */
        if (s_state != EXP_STATE_DISCONNECTED) {
            TickType_t now = xTaskGetTickCount();
            if (s_last_rx_tick != 0 && (now - s_last_rx_tick) > pdMS_TO_TICKS(1500)) {
                ESP_LOGW(TAG, "No RX from Flipper for >1500ms; marking error for reconnect");
                s_state = EXP_STATE_ERROR;
                s_rx_len = 0;
                s_last_rx_tick = now;
            }
        }

        /* Send heartbeat periodically when connected */
        static TickType_t last_heartbeat = 0;
        if (s_state == EXP_STATE_RPC_ACTIVE) {
            TickType_t now = xTaskGetTickCount();
            if ((now - last_heartbeat) > pdMS_TO_TICKS(200)) {
                expansion_send_heartbeat();
                last_heartbeat = now;
            }
        }
    }
}

esp_err_t expansion_init(int tx_pin, int rx_pin, expansion_rpc_rx_callback_t rpc_callback) {
    s_tx_pin = tx_pin;
    s_rx_pin = rx_pin;
    s_rpc_callback = rpc_callback;
    s_current_baud = EXP_INITIAL_BAUD;

    /* Configure UART at initial baud rate */
    uart_config_t uart_config = {
        .baud_rate = EXP_INITIAL_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };

    esp_err_t err = uart_driver_install(UART_NUM, UART_BUF_SIZE * 2, 0, 0, NULL, 0);
    if (err != ESP_OK) return err;

    err = uart_param_config(UART_NUM, &uart_config);
    if (err != ESP_OK) return err;

    err = uart_set_pin(UART_NUM, tx_pin, rx_pin, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
    if (err != ESP_OK) return err;

    s_mutex = xSemaphoreCreateMutex();
    if (!s_mutex) return ESP_ERR_NO_MEM;

    /* Start RX task */
    xTaskCreate(uart_rx_task, "exp_uart_rx", 4096, NULL, 10, &s_rx_task);

    ESP_LOGI(TAG, "Expansion module initialized (TX=%d, RX=%d)", tx_pin, rx_pin);
    return ESP_OK;
}

esp_err_t expansion_connect(void) {
    if (s_state != EXP_STATE_DISCONNECTED && s_state != EXP_STATE_ERROR) {
        return ESP_ERR_INVALID_STATE;
    }

    /* Reset to initial baud */
    set_baud_rate(EXP_INITIAL_BAUD);
    s_rx_len = 0;
    s_last_rx_tick = xTaskGetTickCount();

    /* Signal presence to Flipper */
    s_state = EXP_STATE_AWAITING_HEARTBEAT;
    signal_presence();

    ESP_LOGI(TAG, "Connecting to Flipper...");
    return ESP_OK;
}

esp_err_t expansion_send_rpc(const uint8_t *data, size_t len) {
    if (s_state != EXP_STATE_RPC_ACTIVE) {
        return ESP_ERR_INVALID_STATE;
    }

    /* Send in chunks if needed */
    size_t offset = 0;
    while (offset < len) {
        size_t chunk = len - offset;
        if (chunk > EXP_DATA_MAX_PAYLOAD) {
            chunk = EXP_DATA_MAX_PAYLOAD;
        }

        bridge_stats_inc_exp_tx_data_bytes(chunk);
        esp_err_t err = send_data_frame(data + offset, chunk);
        if (err != ESP_OK) return err;

        offset += chunk;

        /* Wait a bit between chunks for ACK */
        if (offset < len) {
            vTaskDelay(pdMS_TO_TICKS(10));
        }
    }

    return ESP_OK;
}

void expansion_uart_rx(const uint8_t *data, size_t len) {
    /* Data is handled by uart_rx_task */
    (void)data;
    (void)len;
}

expansion_state_t expansion_get_state(void) {
    return s_state;
}

bool expansion_is_connected(void) {
    return s_state == EXP_STATE_RPC_ACTIVE;
}

void expansion_disconnect(void) {
    if (s_state == EXP_STATE_RPC_ACTIVE) {
        send_control(EXP_CONTROL_STOP_RPC);
    }
    s_state = EXP_STATE_DISCONNECTED;
    s_rx_len = 0;
    set_baud_rate(EXP_INITIAL_BAUD);
    ESP_LOGI(TAG, "Disconnected");
}
