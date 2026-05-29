/*
 * TCP <-> UART bridge scaffold for ESP32 WiFi Dev Board.
 *
 * This is intentionally minimal and not a drop-in build for every toolchain.
 * It's a reference starting point for an ESP-IDF style implementation.
 *
 * Fill in:
 * - WiFi provisioning (SSID/password)
 * - UART pins and baud rate matching your Flipper connection
 * - ESP-IDF component boilerplate (CMakeLists, sdkconfig, etc.)
 */

#include <stdint.h>
#include <string.h>

// PSEUDO-CODE ONLY: replace with actual ESP-IDF includes if you build this.
// #include "freertos/FreeRTOS.h"
// #include "freertos/task.h"
// #include "lwip/sockets.h"
// #include "driver/uart.h"
// #include "esp_wifi.h"
// #include "esp_event.h"
// #include "nvs_flash.h"

#define BRIDGE_PORT 8080
#define UART_BAUDRATE 115200

static void wifi_connect_sta(void) {
  // TODO: connect to home WiFi (STA mode)
}

static int tcp_listen_socket(uint16_t port) {
  // TODO: create/bind/listen socket
  // return listen_fd;
  return -1;
}

static void uart_init_bridge(void) {
  // TODO: init UART with correct pins + baud rate.
}

static void forward_tcp_to_uart(int client_fd) {
  // TODO: read() from client_fd, uart_write_bytes()
}

static void forward_uart_to_tcp(int client_fd) {
  // TODO: uart_read_bytes(), send() to client_fd
}

int main(void) {
  // In ESP-IDF this would be app_main(). Kept as main() so it compiles as a stub.
  wifi_connect_sta();
  uart_init_bridge();

  int listen_fd = tcp_listen_socket(BRIDGE_PORT);
  (void)listen_fd;

  // TODO: accept loop:
  // while (1) {
  //   int client_fd = accept(listen_fd, ...);
  //   spawn two tasks: forward_tcp_to_uart and forward_uart_to_tcp
  // }

  return 0;
}
