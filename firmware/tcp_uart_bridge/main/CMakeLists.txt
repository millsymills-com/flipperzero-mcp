idf_component_register(
    SRCS "main.c" "wifi_manager.c" "tcp_server.c" "expansion_module.c" "http_api.c" "bridge_stats.c"
    INCLUDE_DIRS "."
    REQUIRES json esp_http_server driver esp_netif esp_wifi nvs_flash lwip esp_event esp_driver_uart esp_driver_gpio
)
