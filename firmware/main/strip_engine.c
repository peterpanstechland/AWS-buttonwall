#include "strip_engine.h"

#include "esp_check.h"
#include "driver/rmt_encoder.h"
#include "driver/rmt_tx.h"
#include "generated_hw.h"

#define PIXELS (HW_PIXELS_PER_PANEL * 4)
#define BRIGHT_NUM 1
#define BRIGHT_DEN 4

static uint8_t pixels[HW_LANE_COUNT][PIXELS * 3];
static rmt_channel_handle_t channels[HW_LANE_COUNT];
static rmt_encoder_handle_t encoder;

static void scale(uint8_t *value)
{
    *value = (uint8_t)((*value * BRIGHT_NUM) / BRIGHT_DEN);
}

void strip_init(void)
{
    rmt_bytes_encoder_config_t bytes = {
        .bit0 = {.level0 = 1, .duration0 = 3, .level1 = 0, .duration1 = 9},
        .bit1 = {.level0 = 1, .duration0 = 9, .level1 = 0, .duration1 = 3},
        .flags.msb_first = 1,
    };
    ESP_ERROR_CHECK(rmt_new_bytes_encoder(&bytes, &encoder));
    for (int lane = 0; lane < HW_LANE_COUNT; lane++) {
        rmt_tx_channel_config_t tx = {
            .gpio_num = HW_LANE_GPIO[lane],
            .clk_src = RMT_CLK_SRC_DEFAULT,
            .resolution_hz = 10000000,
            .mem_block_symbols = 64,
            .trans_queue_depth = 4,
        };
        ESP_ERROR_CHECK(rmt_new_tx_channel(&tx, &channels[lane]));
        ESP_ERROR_CHECK(rmt_enable(channels[lane]));
    }
}

void strip_fill(int lane, uint8_t r, uint8_t g, uint8_t b)
{
    scale(&r);
    scale(&g);
    scale(&b);
    for (int i = 0; i < PIXELS; i++) {
        pixels[lane][i * 3] = g;
        pixels[lane][i * 3 + 1] = r;
        pixels[lane][i * 3 + 2] = b;
    }
}

void strip_show(void)
{
    rmt_transmit_config_t tx = {.loop_count = 0};
    for (int lane = 0; lane < HW_LANE_COUNT; lane++) {
        rmt_transmit(channels[lane], encoder, pixels[lane], sizeof pixels[lane], &tx);
    }
}
