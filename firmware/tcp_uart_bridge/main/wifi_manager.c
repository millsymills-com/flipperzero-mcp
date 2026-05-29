/**
 * WiFi Manager Implementation
 *
 * Handles WiFi connectivity with captive portal for configuration.
 */

#include "wifi_manager.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_event.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "esp_wifi_types.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "lwip/inet.h"
#include "nvs_flash.h"

static const char *TAG = "wifi_manager";

/* Event group bits */
#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAIL_BIT BIT1

/* NVS keys */
#define NVS_NAMESPACE "wifi_creds"
#define NVS_KEY_SSID "ssid"
#define NVS_KEY_PASS "password"

/* Configuration */
#define MAX_RETRY_COUNT 5
#define WIFI_SCAN_LIST_SIZE 10

/* Build stamp (compile-time) shown in captive portal UI */
#define BUILD_TIMESTAMP (__DATE__ " " __TIME__)

/* State */
static EventGroupHandle_t s_wifi_event_group;
static int s_retry_num = 0;
static bool s_is_connected = false;
static esp_ip4_addr_t s_ip_addr;
static httpd_handle_t s_httpd = NULL;
static esp_netif_t *s_sta_netif = NULL;
static esp_netif_t *s_ap_netif = NULL;

/* HTML for captive portal (served as chunks so '%' in CSS doesn't break printf formatting) */
static const char CAPTIVE_PORTAL_HTML_PREFIX[] =
    "<!DOCTYPE html>"
    "<html><head><meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<title>Flipper Bridge Setup</title>"
    "<style>"
    "body{font-family:sans-serif;margin:20px;background:#1a1a2e;color:#eee;}"
    "h1{color:#ff8c00;}"
    ".container{max-width:400px;margin:0 auto;}"
    "input,select{width:100%;padding:12px;margin:8px 0;box-sizing:border-box;"
    "border:1px solid #444;border-radius:4px;background:#2a2a4e;color:#eee;}"
    "button{width:100%;padding:14px;background:#ff8c00;color:#fff;border:none;"
    "border-radius:4px;cursor:pointer;font-size:16px;margin-top:10px;}"
    "button:hover{background:#e67e00;}"
    ".status{padding:10px;margin:10px 0;border-radius:4px;}"
    ".success{background:#2d5a2d;}"
    ".error{background:#5a2d2d;}"
    ".networks{margin:15px 0;}"
    ".network{padding:10px;margin:5px 0;background:#2a2a4e;border-radius:4px;cursor:pointer;}"
    ".network:hover{background:#3a3a5e;}"
    "</style></head><body>"
    "<div class='container'>"
    "<h1>&#x1F42C; Flipper Bridge</h1>"
    "<p>Configure WiFi connection for TCP-UART bridge</p>"
    "<p style='font-size:12px;opacity:0.8;margin-top:-8px'>Build: ";

static const char CAPTIVE_PORTAL_HTML_SUFFIX[] =
    "</p>"
    "<form action='/connect' method='POST'>"
    "<label>WiFi Network (SSID):</label>"
    "<input type='text' name='ssid' id='ssid' required maxlength='32'>"
    "<label>Password:</label>"
    "<input type='password' name='password' id='password' maxlength='64'>"
    "<button type='submit'>Connect</button>"
    "</form>"
    "<div class='networks' id='networks'></div>"
    "<script>"
    "fetch('/scan').then(r=>r.json()).then(d=>{"
    "let h='<p>Available networks:</p>';"
    "d.forEach(n=>h+='<div class=\"network\" onclick=\"document.getElementById(\\'ssid\\').value=\\''+n.ssid+'\\'\">'+"
    "n.ssid+' ('+n.rssi+' dBm)</div>');"
    "document.getElementById('networks').innerHTML=h;});"
    "</script>"
    "</div></body></html>";

static const char CONNECT_SUCCESS_HTML[] =
    "<!DOCTYPE html>"
    "<html><head><meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<title>Connected</title>"
    "<style>"
    "body{font-family:sans-serif;margin:20px;background:#1a1a2e;color:#eee;text-align:center;}"
    "h1{color:#4CAF50;}"
    "</style></head><body>"
    "<h1>&#x2705; Connected!</h1>"
    "<p>The bridge is now connecting to your WiFi network.</p>"
    "<p>IP Address: %s</p>"
    "<p>TCP Port: %d</p>"
    "<p>You can close this page.</p>"
    "</body></html>";

static const char CONNECT_FAIL_HTML[] =
    "<!DOCTYPE html>"
    "<html><head><meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<meta http-equiv='refresh' content='3;url=/'>"
    "<title>Connection Failed</title>"
    "<style>"
    "body{font-family:sans-serif;margin:20px;background:#1a1a2e;color:#eee;text-align:center;}"
    "h1{color:#f44336;}"
    "</style></head><body>"
    "<h1>&#x274C; Connection Failed</h1>"
    "<p>Could not connect to the WiFi network.</p>"
    "<p>Redirecting back to setup...</p>"
    "</body></html>";

/* Forward declarations */
static void wifi_event_handler(void *arg, esp_event_base_t event_base,
                               int32_t event_id, void *event_data);
static esp_err_t start_captive_portal(void);
static void stop_captive_portal(void);

/* URL decode helper - decodes %XX and + to original characters */
static void url_decode(char *dst, const char *src, size_t dst_size) {
    size_t di = 0;
    size_t si = 0;
    while (src[si] && di < dst_size - 1) {
        if (src[si] == '%' && src[si + 1] && src[si + 2]) {
            char hex[3] = {src[si + 1], src[si + 2], 0};
            dst[di++] = (char)strtol(hex, NULL, 16);
            si += 3;
        } else if (src[si] == '+') {
            dst[di++] = ' ';
            si++;
        } else {
            dst[di++] = src[si++];
        }
    }
    dst[di] = '\0';
}

/* Load credentials from NVS */
static esp_err_t load_credentials(char *ssid, size_t ssid_len,
                                   char *password, size_t pass_len) {
    nvs_handle_t nvs;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READONLY, &nvs);
    if (err != ESP_OK) return err;

    size_t len = ssid_len;
    err = nvs_get_str(nvs, NVS_KEY_SSID, ssid, &len);
    if (err != ESP_OK) {
        nvs_close(nvs);
        return err;
    }

    len = pass_len;
    err = nvs_get_str(nvs, NVS_KEY_PASS, password, &len);
    nvs_close(nvs);
    return err;
}

/* Save credentials to NVS */
static esp_err_t save_credentials(const char *ssid, const char *password) {
    nvs_handle_t nvs;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &nvs);
    if (err != ESP_OK) return err;

    err = nvs_set_str(nvs, NVS_KEY_SSID, ssid);
    if (err != ESP_OK) {
        nvs_close(nvs);
        return err;
    }

    err = nvs_set_str(nvs, NVS_KEY_PASS, password);
    if (err == ESP_OK) {
        err = nvs_commit(nvs);
    }
    nvs_close(nvs);
    return err;
}

/* WiFi event handler */
static void wifi_event_handler(void *arg, esp_event_base_t event_base,
                               int32_t event_id, void *event_data) {
    if (event_base == WIFI_EVENT) {
        if (event_id == WIFI_EVENT_STA_START) {
            esp_wifi_connect();
        } else if (event_id == WIFI_EVENT_STA_DISCONNECTED) {
            s_is_connected = false;
            if (s_retry_num < MAX_RETRY_COUNT) {
                esp_wifi_connect();
                s_retry_num++;
                ESP_LOGI(TAG, "Retrying connection (%d/%d)", s_retry_num,
                         MAX_RETRY_COUNT);
            } else {
                xEventGroupSetBits(s_wifi_event_group, WIFI_FAIL_BIT);
                ESP_LOGI(TAG, "Connection failed, starting captive portal");
            }
        } else if (event_id == WIFI_EVENT_AP_STACONNECTED) {
            ESP_LOGI(TAG, "Station joined AP");
        } else if (event_id == WIFI_EVENT_AP_STADISCONNECTED) {
            ESP_LOGI(TAG, "Station left AP");
        }
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *)event_data;
        s_ip_addr = event->ip_info.ip;
        ESP_LOGI(TAG, "Got IP: " IPSTR, IP2STR(&s_ip_addr));
        s_retry_num = 0;
        s_is_connected = true;
        xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
    }
}

/* HTTP handlers for captive portal */
static esp_err_t http_get_handler(httpd_req_t *req) {
    httpd_resp_set_type(req, "text/html");
    httpd_resp_sendstr_chunk(req, CAPTIVE_PORTAL_HTML_PREFIX);
    httpd_resp_sendstr_chunk(req, BUILD_TIMESTAMP);
    httpd_resp_sendstr_chunk(req, CAPTIVE_PORTAL_HTML_SUFFIX);
    httpd_resp_sendstr_chunk(req, NULL); /* end response */
    return ESP_OK;
}

static esp_err_t http_scan_handler(httpd_req_t *req) {
    wifi_ap_record_t ap_records[WIFI_SCAN_LIST_SIZE];
    uint16_t ap_count = WIFI_SCAN_LIST_SIZE;

    esp_wifi_scan_start(NULL, true);
    esp_wifi_scan_get_ap_records(&ap_count, ap_records);

    char json[1024] = "[";
    for (int i = 0; i < ap_count && i < WIFI_SCAN_LIST_SIZE; i++) {
        char entry[128];
        snprintf(entry, sizeof(entry),
                 "%s{\"ssid\":\"%s\",\"rssi\":%d}",
                 i > 0 ? "," : "",
                 (char *)ap_records[i].ssid,
                 ap_records[i].rssi);
        strncat(json, entry, sizeof(json) - strlen(json) - 1);
    }
    strncat(json, "]", sizeof(json) - strlen(json) - 1);

    httpd_resp_set_type(req, "application/json");
    httpd_resp_send(req, json, HTTPD_RESP_USE_STRLEN);
    return ESP_OK;
}

static esp_err_t http_connect_handler(httpd_req_t *req) {
    char buf[256];
    int ret = httpd_req_recv(req, buf, sizeof(buf) - 1);
    if (ret <= 0) {
        httpd_resp_send_500(req);
        return ESP_FAIL;
    }
    buf[ret] = '\0';

    /* Parse SSID and password from form data */
    char ssid[33] = {0};
    char password[65] = {0};
    char temp[128] = {0};

    char *ssid_start = strstr(buf, "ssid=");
    char *pass_start = strstr(buf, "password=");

    if (ssid_start) {
        ssid_start += 5;
        char *ssid_end = strchr(ssid_start, '&');
        size_t len = ssid_end ? (size_t)(ssid_end - ssid_start) : strlen(ssid_start);
        if (len > sizeof(temp) - 1) len = sizeof(temp) - 1;
        strncpy(temp, ssid_start, len);
        temp[len] = '\0';
        url_decode(ssid, temp, sizeof(ssid));
    }

    if (pass_start) {
        pass_start += 9;
        char *pass_end = strchr(pass_start, '&');
        size_t len = pass_end ? (size_t)(pass_end - pass_start) : strlen(pass_start);
        if (len > sizeof(temp) - 1) len = sizeof(temp) - 1;
        strncpy(temp, pass_start, len);
        temp[len] = '\0';
        url_decode(password, temp, sizeof(password));
    }

    if (strlen(ssid) == 0) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "SSID required");
        return ESP_FAIL;
    }

    ESP_LOGI(TAG, "Attempting connection to SSID: %s", ssid);

    /* Save credentials */
    save_credentials(ssid, password);

    /* Configure and connect */
    wifi_config_t wifi_config = {0};
    strncpy((char *)wifi_config.sta.ssid, ssid, sizeof(wifi_config.sta.ssid) - 1);
    strncpy((char *)wifi_config.sta.password, password,
            sizeof(wifi_config.sta.password) - 1);

    esp_wifi_set_mode(WIFI_MODE_APSTA);
    esp_wifi_set_config(WIFI_IF_STA, &wifi_config);

    s_retry_num = 0;
    xEventGroupClearBits(s_wifi_event_group, WIFI_CONNECTED_BIT | WIFI_FAIL_BIT);
    esp_wifi_connect();

    /* Wait for connection result */
    EventBits_t bits = xEventGroupWaitBits(s_wifi_event_group,
                                           WIFI_CONNECTED_BIT | WIFI_FAIL_BIT,
                                           pdFALSE, pdFALSE, pdMS_TO_TICKS(15000));

    httpd_resp_set_type(req, "text/html");
    if (bits & WIFI_CONNECTED_BIT) {
        char response[512];
        char ip_str[16];
        snprintf(ip_str, sizeof(ip_str), IPSTR, IP2STR(&s_ip_addr));
        snprintf(response, sizeof(response), CONNECT_SUCCESS_HTML, ip_str,
                 CONFIG_BRIDGE_TCP_PORT);
        httpd_resp_send(req, response, HTTPD_RESP_USE_STRLEN);

        /* Stop AP after successful connection */
        vTaskDelay(pdMS_TO_TICKS(2000));
        stop_captive_portal();
        esp_wifi_set_mode(WIFI_MODE_STA);
    } else {
        httpd_resp_send(req, CONNECT_FAIL_HTML, HTTPD_RESP_USE_STRLEN);
    }

    return ESP_OK;
}

/* Captive portal redirect handler */
static esp_err_t http_redirect_handler(httpd_req_t *req) {
    httpd_resp_set_status(req, "302 Found");
    httpd_resp_set_hdr(req, "Location", "http://192.168.4.1/");
    httpd_resp_send(req, NULL, 0);
    return ESP_OK;
}

static esp_err_t start_captive_portal(void) {
    if (s_httpd != NULL) return ESP_OK;

    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.uri_match_fn = httpd_uri_match_wildcard;
    config.lru_purge_enable = true;
    config.max_uri_handlers = 8;

    esp_err_t err = httpd_start(&s_httpd, &config);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Failed to start HTTP server: %s", esp_err_to_name(err));
        return err;
    }

    /* Register URI handlers */
    httpd_uri_t root = {.uri = "/", .method = HTTP_GET, .handler = http_get_handler};
    httpd_uri_t scan = {.uri = "/scan", .method = HTTP_GET, .handler = http_scan_handler};
    httpd_uri_t connect = {.uri = "/connect", .method = HTTP_POST, .handler = http_connect_handler};
    httpd_uri_t redirect = {.uri = "/*", .method = HTTP_GET, .handler = http_redirect_handler};

    httpd_register_uri_handler(s_httpd, &root);
    httpd_register_uri_handler(s_httpd, &scan);
    httpd_register_uri_handler(s_httpd, &connect);
    httpd_register_uri_handler(s_httpd, &redirect);

    ESP_LOGI(TAG, "Captive portal started on http://192.168.4.1/");
    return ESP_OK;
}

static void stop_captive_portal(void) {
    if (s_httpd) {
        httpd_stop(s_httpd);
        s_httpd = NULL;
        ESP_LOGI(TAG, "Captive portal stopped");
    }
}

esp_err_t wifi_manager_init(void) {
    esp_err_t err;

    /* Initialize NVS */
    err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        err = nvs_flash_init();
    }
    if (err != ESP_OK) return err;

    /* Create event group */
    s_wifi_event_group = xEventGroupCreate();

    /* Initialize TCP/IP stack */
    err = esp_netif_init();
    if (err != ESP_OK) return err;

    err = esp_event_loop_create_default();
    if (err != ESP_OK) return err;

    /* Create network interfaces */
    s_sta_netif = esp_netif_create_default_wifi_sta();
    s_ap_netif = esp_netif_create_default_wifi_ap();

    /* Initialize WiFi */
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    err = esp_wifi_init(&cfg);
    if (err != ESP_OK) return err;

    /* Register event handlers */
    esp_event_handler_instance_t instance_any_id;
    esp_event_handler_instance_t instance_got_ip;
    esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                        &wifi_event_handler, NULL, &instance_any_id);
    esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                        &wifi_event_handler, NULL, &instance_got_ip);

    /* Try to load stored credentials */
    char ssid[33] = {0};
    char password[65] = {0};
    err = load_credentials(ssid, sizeof(ssid), password, sizeof(password));

    if (err == ESP_OK && strlen(ssid) > 0) {
        ESP_LOGI(TAG, "Found stored credentials for SSID: %s", ssid);

        /* Configure STA mode with stored credentials */
        wifi_config_t wifi_config = {0};
        strncpy((char *)wifi_config.sta.ssid, ssid, sizeof(wifi_config.sta.ssid) - 1);
        strncpy((char *)wifi_config.sta.password, password,
                sizeof(wifi_config.sta.password) - 1);

        esp_wifi_set_mode(WIFI_MODE_STA);
        esp_wifi_set_config(WIFI_IF_STA, &wifi_config);
        esp_wifi_start();

        /* Wait for connection */
        EventBits_t bits = xEventGroupWaitBits(s_wifi_event_group,
                                               WIFI_CONNECTED_BIT | WIFI_FAIL_BIT,
                                               pdFALSE, pdFALSE, pdMS_TO_TICKS(10000));

        if (bits & WIFI_CONNECTED_BIT) {
            ESP_LOGI(TAG, "Connected to stored network");
            return ESP_OK;
        }
        ESP_LOGW(TAG, "Could not connect to stored network, starting captive portal");
    } else {
        ESP_LOGI(TAG, "No stored credentials, starting captive portal");
    }

    /* Start AP mode for captive portal */
    wifi_config_t ap_config = {
        .ap = {
            .ssid = CONFIG_BRIDGE_AP_SSID,
            .ssid_len = strlen(CONFIG_BRIDGE_AP_SSID),
            .password = CONFIG_BRIDGE_AP_PASSWORD,
            .max_connection = 4,
            .authmode = WIFI_AUTH_WPA2_PSK,
        },
    };

    if (strlen(CONFIG_BRIDGE_AP_PASSWORD) < 8) {
        ap_config.ap.authmode = WIFI_AUTH_OPEN;
    }

    esp_wifi_set_mode(WIFI_MODE_APSTA);
    esp_wifi_set_config(WIFI_IF_AP, &ap_config);
    esp_wifi_start();

    start_captive_portal();

    return ESP_OK;
}

bool wifi_manager_is_connected(void) {
    return s_is_connected;
}

esp_err_t wifi_manager_get_ip(char *buf, size_t buf_len) {
    if (!s_is_connected || buf == NULL || buf_len < 16) {
        return ESP_ERR_INVALID_STATE;
    }
    snprintf(buf, buf_len, IPSTR, IP2STR(&s_ip_addr));
    return ESP_OK;
}

esp_err_t wifi_manager_reset_credentials(void) {
    nvs_handle_t nvs;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &nvs);
    if (err != ESP_OK) return err;

    nvs_erase_key(nvs, NVS_KEY_SSID);
    nvs_erase_key(nvs, NVS_KEY_PASS);
    nvs_commit(nvs);
    nvs_close(nvs);

    ESP_LOGI(TAG, "Credentials cleared, restarting...");
    esp_restart();
    return ESP_OK;
}
