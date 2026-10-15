#pragma once
#include <stdint.h>
#define HW_REVISION "v0.8"
#define HW_PIXELS_PER_PANEL 32
#define HW_OE_GPIO 42
#define HW_I2C_SDA_GPIO 47
#define HW_I2C_SCL_GPIO 3
#define HW_MCP23017_ADDR 32
#define HW_BUTTON_COUNT 17
#define HW_LANE_COUNT 4
static const int HW_BUTTON_GPIO[HW_BUTTON_COUNT] = {
    39, 11, 12, 13, 14, 18, 8, 9, 10, 4, 15, 16, 17, 21, 5, 6, 7
};
static const int HW_LANE_GPIO[HW_LANE_COUNT] = {
    1, 2, 41, 40
};
static const int8_t HW_LAMP_BIT[HW_BUTTON_COUNT] = {
    -1, 0, 1, 2, 3, 7, 6, 5, 4, 8, 9, 10, 11, 12, 13, 14, 15
};
static const char *HW_BUTTON_NAME[HW_BUTTON_COUNT] = {
    "START", "A1", "A2", "A3", "A4", "B1", "B2", "B3", "B4", "C1", "C2", "C3", "C4", "D1", "D2", "D3", "D4"
};
static const int HW_BUTTON_LANE[HW_BUTTON_COUNT] = {
    -1, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3
};
