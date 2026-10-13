#include "awg1.h"
#include "input_scan.h"
#include "strip_engine.h"

#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"

static const char *TAG = "aws_wall";

void app_main(void)
{
    esp_err_t nvs = nvs_flash_init();
    if (nvs == ESP_ERR_NVS_NO_FREE_PAGES || nvs == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ESP_ERROR_CHECK(nvs_flash_init());
    }
    input_scan_init();
    strip_init();
    strip_show();
    uint8_t hello[256];
    size_t n = awg1_encode(hello, sizeof hello, 0x01, 1, true,
                           "{\"device_id\":\"wall-mcu-01\",\"proto_major\":1,\"proto_minor\":2}");
    ESP_LOGI(TAG, "boot dark, hello frame %u bytes, logs stay on UART", (unsigned)n);
    while (true) {
        input_scan_tick(esp_timer_get_time());
        input_event_t event;
        while (input_pop(&event)) {
            if (event.down) {
                ESP_LOGI(TAG, "button %u raw %llu", event.button_id, (unsigned long long)event.raw_us);
            }
        }
        vTaskDelay(pdMS_TO_TICKS(1));
    }
}
