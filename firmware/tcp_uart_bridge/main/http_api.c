/**
 * HTTP API for Flipper Zero WiFi Bridge
 *
 * Provides status endpoints and will eventually support RPC commands.
 * CLI-based commands are not yet implemented (requires Protobuf RPC translation).
 */

#include "http_api.h"
#include "expansion_module.h"
#include "bridge_stats.h"

#include <string.h>
#include <stdlib.h>

#include "esp_log.h"
#include "esp_http_server.h"
#include "cJSON.h"

static const char *TAG = "http_api";

static httpd_handle_t s_server = NULL;

/* CORS headers for browser access */
static esp_err_t set_cors_headers(httpd_req_t *req) {
    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
    httpd_resp_set_hdr(req, "Access-Control-Allow-Methods", "GET, POST, OPTIONS");
    httpd_resp_set_hdr(req, "Access-Control-Allow-Headers", "Content-Type");
    return ESP_OK;
}

/* Handle CORS preflight */
static esp_err_t options_handler(httpd_req_t *req) {
    set_cors_headers(req);
    httpd_resp_send(req, NULL, 0);
    return ESP_OK;
}

/* GET /api/health - Bridge health and connection status */
static esp_err_t health_handler(httpd_req_t *req) {
    set_cors_headers(req);
    httpd_resp_set_type(req, "application/json");

    bool connected = expansion_is_connected();
    expansion_state_t state = expansion_get_state();

    const char *state_str;
    switch (state) {
        case EXP_STATE_DISCONNECTED: state_str = "disconnected"; break;
        case EXP_STATE_AWAITING_HEARTBEAT: state_str = "awaiting_heartbeat"; break;
        case EXP_STATE_BAUD_NEGOTIATION: state_str = "baud_negotiation"; break;
        case EXP_STATE_RPC_STARTING: state_str = "rpc_starting"; break;
        case EXP_STATE_RPC_ACTIVE: state_str = "rpc_active"; break;
        case EXP_STATE_ERROR: state_str = "error"; break;
        default: state_str = "unknown"; break;
    }

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddStringToObject(resp, "status", connected ? "ok" : "connecting");
    cJSON_AddStringToObject(resp, "bridge", "flipper-expansion-http");
    cJSON_AddStringToObject(resp, "version", "2.0.0");
    cJSON_AddBoolToObject(resp, "flipper_connected", connected);
    cJSON_AddStringToObject(resp, "connection_state", state_str);

    char *json = cJSON_PrintUnformatted(resp);
    httpd_resp_sendstr(req, json);

    free(json);
    cJSON_Delete(resp);
    return ESP_OK;
}

/* GET /api/status - Detailed status */
static esp_err_t status_handler(httpd_req_t *req) {
    set_cors_headers(req);
    httpd_resp_set_type(req, "application/json");

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "flipper_connected", expansion_is_connected());
    cJSON_AddNumberToObject(resp, "connection_state", expansion_get_state());

    cJSON *capabilities = cJSON_CreateArray();
    if (expansion_is_connected()) {
        cJSON_AddItemToArray(capabilities, cJSON_CreateString("protobuf_rpc"));
        cJSON_AddItemToArray(capabilities, cJSON_CreateString("tcp_forward"));
    }
    cJSON_AddItemToObject(resp, "capabilities", capabilities);

    cJSON_AddStringToObject(resp, "note", "Use TCP port 8080 for raw Protobuf RPC");

    char *json = cJSON_PrintUnformatted(resp);
    httpd_resp_sendstr(req, json);

    free(json);
    cJSON_Delete(resp);
    return ESP_OK;
}

/* GET /api/debug/counters - low-level counters for debugging the bridge */
static esp_err_t debug_counters_handler(httpd_req_t *req) {
    set_cors_headers(req);
    httpd_resp_set_type(req, "application/json");

    bridge_counters_t c;
    bridge_stats_snapshot(&c);

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "flipper_connected", expansion_is_connected());
    cJSON_AddStringToObject(resp, "connection_state", "see /api/health for state string");

    cJSON *tcp = cJSON_CreateObject();
    cJSON_AddNumberToObject(tcp, "rx_bytes", c.tcp_rx_bytes);
    cJSON_AddNumberToObject(tcp, "tx_bytes", c.tcp_tx_bytes);
    cJSON_AddNumberToObject(tcp, "rx_packets", c.tcp_rx_packets);
    cJSON_AddNumberToObject(tcp, "tx_packets", c.tcp_tx_packets);
    cJSON_AddNumberToObject(tcp, "clients_accepted", c.tcp_clients_accepted);
    cJSON_AddNumberToObject(tcp, "clients_closed", c.tcp_clients_closed);
    cJSON_AddItemToObject(resp, "tcp", tcp);

    cJSON *exp = cJSON_CreateObject();
    cJSON_AddNumberToObject(exp, "tx_frames", c.exp_tx_frames);
    cJSON_AddNumberToObject(exp, "rx_frames", c.exp_rx_frames);
    cJSON_AddNumberToObject(exp, "tx_data_bytes", c.exp_tx_data_bytes);
    cJSON_AddNumberToObject(exp, "rx_data_bytes", c.exp_rx_data_bytes);
    cJSON_AddNumberToObject(exp, "checksum_failures", c.exp_checksum_failures);
    cJSON_AddNumberToObject(exp, "unknown_frames", c.exp_unknown_frames);
    cJSON_AddNumberToObject(exp, "last_status", c.exp_last_status);
    cJSON_AddNumberToObject(exp, "last_frame_type", c.exp_last_frame_type);
    cJSON_AddItemToObject(resp, "expansion", exp);

    char *json = cJSON_PrintUnformatted(resp);
    httpd_resp_sendstr(req, json);

    free(json);
    cJSON_Delete(resp);
    return ESP_OK;
}

/* POST /api/debug/reconnect - force reconnect to Flipper Expansion RPC */
static esp_err_t debug_reconnect_handler(httpd_req_t *req) {
    set_cors_headers(req);
    httpd_resp_set_type(req, "application/json");

    expansion_disconnect();
    // best-effort immediate reconnect; the main task will also keep retrying
    (void)expansion_connect();

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "success", true);
    cJSON_AddStringToObject(resp, "message", "Reconnect requested");
    char *json = cJSON_PrintUnformatted(resp);
    httpd_resp_sendstr(req, json);
    free(json);
    cJSON_Delete(resp);
    return ESP_OK;
}

/* Placeholder for future RPC-based endpoints */
static esp_err_t not_implemented_handler(httpd_req_t *req) {
    set_cors_headers(req);
    httpd_resp_set_type(req, "application/json");

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "success", false);
    cJSON_AddStringToObject(resp, "error", "Not yet implemented - use TCP:8080 for Protobuf RPC");

    char *json = cJSON_PrintUnformatted(resp);
    httpd_resp_sendstr(req, json);

    free(json);
    cJSON_Delete(resp);
    return ESP_OK;
}

esp_err_t http_api_init(uint16_t port) {
    if (s_server != NULL) {
        ESP_LOGW(TAG, "HTTP API already running");
        return ESP_OK;
    }

    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.server_port = port;
    config.uri_match_fn = httpd_uri_match_wildcard;
    config.max_uri_handlers = 16;
    config.lru_purge_enable = true;

    esp_err_t err = httpd_start(&s_server, &config);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Failed to start HTTP server: %s", esp_err_to_name(err));
        return err;
    }

    /* Register URI handlers */
    httpd_uri_t health = {.uri = "/api/health", .method = HTTP_GET, .handler = health_handler};
    httpd_uri_t status = {.uri = "/api/status", .method = HTTP_GET, .handler = status_handler};
    httpd_uri_t debug = {.uri = "/api/debug/counters", .method = HTTP_GET, .handler = debug_counters_handler};
    httpd_uri_t debug_reconnect = {.uri = "/api/debug/reconnect", .method = HTTP_POST, .handler = debug_reconnect_handler};

    /* Placeholder endpoints - will be implemented with Protobuf RPC */
    httpd_uri_t device = {.uri = "/api/device/info", .method = HTTP_GET, .handler = not_implemented_handler};
    httpd_uri_t list = {.uri = "/api/storage/list", .method = HTTP_GET, .handler = not_implemented_handler};
    httpd_uri_t read_f = {.uri = "/api/storage/read", .method = HTTP_GET, .handler = not_implemented_handler};
    httpd_uri_t write_f = {.uri = "/api/storage/write", .method = HTTP_POST, .handler = not_implemented_handler};
    httpd_uri_t delete_f = {.uri = "/api/storage/delete", .method = HTTP_POST, .handler = not_implemented_handler};
    httpd_uri_t mkdir_f = {.uri = "/api/storage/mkdir", .method = HTTP_POST, .handler = not_implemented_handler};
    httpd_uri_t app = {.uri = "/api/app/start", .method = HTTP_POST, .handler = not_implemented_handler};
    httpd_uri_t cli = {.uri = "/api/cli/command", .method = HTTP_POST, .handler = not_implemented_handler};

    /* CORS preflight */
    httpd_uri_t opt = {.uri = "/api/*", .method = HTTP_OPTIONS, .handler = options_handler};

    httpd_register_uri_handler(s_server, &health);
    httpd_register_uri_handler(s_server, &status);
    httpd_register_uri_handler(s_server, &debug);
    httpd_register_uri_handler(s_server, &debug_reconnect);
    httpd_register_uri_handler(s_server, &device);
    httpd_register_uri_handler(s_server, &list);
    httpd_register_uri_handler(s_server, &read_f);
    httpd_register_uri_handler(s_server, &write_f);
    httpd_register_uri_handler(s_server, &delete_f);
    httpd_register_uri_handler(s_server, &mkdir_f);
    httpd_register_uri_handler(s_server, &app);
    httpd_register_uri_handler(s_server, &cli);
    httpd_register_uri_handler(s_server, &opt);

    ESP_LOGI(TAG, "HTTP API started on port %d", port);
    return ESP_OK;
}

void http_api_stop(void) {
    if (s_server) {
        httpd_stop(s_server);
        s_server = NULL;
    }
}

bool http_api_is_running(void) {
    return s_server != NULL;
}

void http_api_uart_rx(const uint8_t *data, size_t len) {
    /* Not used in expansion module mode */
    (void)data;
    (void)len;
}
