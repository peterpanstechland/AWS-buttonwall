#include "bringup.h"
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
    ESP_LOGI(TAG, "boot dark; BW bench and BW3 game transport on native USB");
    esp_log_level_set("*", ESP_LOG_WARN);
    bringup_init();
    while (true) {
        uint64_t now = esp_timer_get_time();
        input_scan_tick(now);
        bringup_poll(now);
        /* At 100 Hz, pdMS_TO_TICKS(1) is zero and starves IDLE0. */
        vTaskDelay(1);
    }
}
