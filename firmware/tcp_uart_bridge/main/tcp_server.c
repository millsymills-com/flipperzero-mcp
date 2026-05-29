/**
 * TCP Server Implementation
 *
 * Manages TCP client connections and data forwarding.
 */

#include "tcp_server.h"

#include <string.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <errno.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"

#include "bridge_stats.h"

static const char *TAG = "tcp_server";

#define RX_BUFFER_SIZE 2048
#define ACCEPT_TASK_STACK_SIZE 4096
#define RX_TASK_STACK_SIZE 4096

/* State */
static int s_listen_sock = -1;
static int s_client_sock = -1;
static tcp_rx_callback_t s_rx_callback = NULL;
static TaskHandle_t s_accept_task = NULL;
static TaskHandle_t s_rx_task = NULL;
static SemaphoreHandle_t s_client_mutex = NULL;
static volatile bool s_running = false;
static volatile uint32_t s_client_generation = 0;

typedef struct {
    int sock;
    uint32_t gen;
} rx_task_args_t;

/* Forward declarations */
static void accept_task(void *arg);
static void rx_task(void *arg);

esp_err_t tcp_server_init(uint16_t port, tcp_rx_callback_t rx_callback) {
    if (s_running) {
        ESP_LOGW(TAG, "Server already running");
        return ESP_ERR_INVALID_STATE;
    }

    s_rx_callback = rx_callback;
    s_client_mutex = xSemaphoreCreateMutex();
    if (s_client_mutex == NULL) {
        ESP_LOGE(TAG, "Failed to create mutex");
        return ESP_ERR_NO_MEM;
    }

    /* Create listening socket */
    s_listen_sock = socket(AF_INET, SOCK_STREAM, IPPROTO_IP);
    if (s_listen_sock < 0) {
        ESP_LOGE(TAG, "Failed to create socket: errno %d", errno);
        return ESP_FAIL;
    }

    /* Set socket options */
    int opt = 1;
    setsockopt(s_listen_sock, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    /* Bind to port */
    struct sockaddr_in addr = {
        .sin_family = AF_INET,
        .sin_addr.s_addr = htonl(INADDR_ANY),
        .sin_port = htons(port),
    };

    if (bind(s_listen_sock, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        ESP_LOGE(TAG, "Failed to bind socket: errno %d", errno);
        close(s_listen_sock);
        s_listen_sock = -1;
        return ESP_FAIL;
    }

    /* Start listening */
    if (listen(s_listen_sock, 1) != 0) {
        ESP_LOGE(TAG, "Failed to listen: errno %d", errno);
        close(s_listen_sock);
        s_listen_sock = -1;
        return ESP_FAIL;
    }

    s_running = true;

    /* Start accept task */
    xTaskCreate(accept_task, "tcp_accept", ACCEPT_TASK_STACK_SIZE, NULL, 5, &s_accept_task);

    ESP_LOGI(TAG, "TCP server listening on port %d", port);
    return ESP_OK;
}

static void accept_task(void *arg) {
    ESP_LOGI(TAG, "Accept task started");

    while (s_running) {
        struct sockaddr_in client_addr;
        socklen_t addr_len = sizeof(client_addr);

        ESP_LOGI(TAG, "Waiting for client connection...");
        int new_sock = accept(s_listen_sock, (struct sockaddr *)&client_addr, &addr_len);

        if (new_sock < 0) {
            if (s_running) {
                ESP_LOGE(TAG, "Accept failed: errno %d", errno);
            }
            continue;
        }

        char addr_str[INET_ADDRSTRLEN];
        inet_ntoa_r(client_addr.sin_addr, addr_str, sizeof(addr_str));
        ESP_LOGI(TAG, "Client connected from %s:%d", addr_str, ntohs(client_addr.sin_port));
        bridge_stats_inc_tcp_clients_accepted(1);

        /* Close existing client if any (RX task will exit on socket close). */
        xSemaphoreTake(s_client_mutex, portMAX_DELAY);
        if (s_client_sock >= 0) {
            ESP_LOGI(TAG, "Closing previous client connection");
            close(s_client_sock);
            s_client_sock = -1;
        }
        s_client_sock = new_sock;
        s_client_generation++;
        uint32_t gen = s_client_generation;
        xSemaphoreGive(s_client_mutex);

        /* Set socket options for low latency */
        int flag = 1;
        setsockopt(new_sock, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(flag));

        /* Set receive timeout */
        struct timeval tv = {.tv_sec = 1, .tv_usec = 0};
        setsockopt(new_sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

        /* Start RX task for this client */
        rx_task_args_t *args = (rx_task_args_t *)malloc(sizeof(rx_task_args_t));
        if (!args) {
            ESP_LOGE(TAG, "Out of memory creating RX task args; closing client");
            xSemaphoreTake(s_client_mutex, portMAX_DELAY);
            if (s_client_sock == new_sock) {
                close(s_client_sock);
                s_client_sock = -1;
            } else {
                close(new_sock);
            }
            xSemaphoreGive(s_client_mutex);
            continue;
        }
        args->sock = new_sock;
        args->gen = gen;

        TaskHandle_t task = NULL;
        BaseType_t ok = xTaskCreate(rx_task, "tcp_rx", RX_TASK_STACK_SIZE, args, 6, &task);
        if (ok != pdPASS) {
            ESP_LOGE(TAG, "Failed to create RX task; closing client");
            free(args);
            xSemaphoreTake(s_client_mutex, portMAX_DELAY);
            if (s_client_sock == new_sock) {
                close(s_client_sock);
                s_client_sock = -1;
            } else {
                close(new_sock);
            }
            xSemaphoreGive(s_client_mutex);
            continue;
        }

        xSemaphoreTake(s_client_mutex, portMAX_DELAY);
        s_rx_task = task;
        xSemaphoreGive(s_client_mutex);
    }

    ESP_LOGI(TAG, "Accept task exiting");
    vTaskDelete(NULL);
}

static void rx_task(void *arg) {
    rx_task_args_t *args = (rx_task_args_t *)arg;
    const int sock = args ? args->sock : -1;
    const uint32_t gen = args ? args->gen : 0;
    free(args);

    uint8_t rx_buffer[RX_BUFFER_SIZE];

    ESP_LOGI(TAG, "RX task started");

    while (s_running && sock >= 0) {
        int len = recv(sock, rx_buffer, sizeof(rx_buffer), 0);

        if (len < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                /* Timeout, continue */
                continue;
            }
            ESP_LOGE(TAG, "recv failed: errno %d", errno);
            break;
        } else if (len == 0) {
            ESP_LOGI(TAG, "Client disconnected");
            break;
        }

        ESP_LOGD(TAG, "Received %d bytes from TCP", len);
        bridge_stats_inc_tcp_rx_packets(1);
        bridge_stats_inc_tcp_rx((size_t)len);

        /* Forward to callback */
        if (s_rx_callback) {
            s_rx_callback(rx_buffer, len);
        }
    }

    /* Clean up: close our socket, and clear global only if we are still current. */
    xSemaphoreTake(s_client_mutex, portMAX_DELAY);
    if (s_client_sock == sock && s_client_generation == gen) {
        close(s_client_sock);
        s_client_sock = -1;
    } else {
        /* Socket may already be closed/replaced; close our handle defensively. */
        close(sock);
    }
    if (s_rx_task == xTaskGetCurrentTaskHandle()) {
        s_rx_task = NULL;
    }
    xSemaphoreGive(s_client_mutex);

    bridge_stats_inc_tcp_clients_closed(1);
    ESP_LOGI(TAG, "RX task exiting");
    vTaskDelete(NULL);
}

int tcp_server_send(const uint8_t *data, size_t len) {
    if (data == NULL || len == 0) {
        return 0;
    }

    xSemaphoreTake(s_client_mutex, portMAX_DELAY);
    int sock = s_client_sock;
    xSemaphoreGive(s_client_mutex);

    if (sock < 0) {
        ESP_LOGD(TAG, "No client connected, dropping %u bytes", (unsigned int)len);
        return -1;
    }

    int sent = send(sock, data, len, 0);
    if (sent < 0) {
        ESP_LOGE(TAG, "send failed: errno %d", errno);
        return -1;
    }

    ESP_LOGD(TAG, "Sent %d bytes to TCP client", sent);
    bridge_stats_inc_tcp_tx_packets(1);
    bridge_stats_inc_tcp_tx((size_t)sent);
    return sent;
}

bool tcp_server_has_client(void) {
    xSemaphoreTake(s_client_mutex, portMAX_DELAY);
    bool has_client = (s_client_sock >= 0);
    xSemaphoreGive(s_client_mutex);
    return has_client;
}

void tcp_server_stop(void) {
    if (!s_running) return;

    ESP_LOGI(TAG, "Stopping TCP server");
    s_running = false;

    /* Close client socket */
    xSemaphoreTake(s_client_mutex, portMAX_DELAY);
    if (s_client_sock >= 0) {
        close(s_client_sock);
        s_client_sock = -1;
    }
    xSemaphoreGive(s_client_mutex);

    /* Close listen socket */
    if (s_listen_sock >= 0) {
        close(s_listen_sock);
        s_listen_sock = -1;
    }

    /* Wait for tasks to exit */
    vTaskDelay(pdMS_TO_TICKS(100));

    if (s_client_mutex) {
        vSemaphoreDelete(s_client_mutex);
        s_client_mutex = NULL;
    }

    ESP_LOGI(TAG, "TCP server stopped");
}
