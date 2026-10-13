#pragma once
#include <stdint.h>
#define HW_REVISION "v0.8"
#define HW_PIXELS_PER_PANEL 32
#define HW_OE_GPIO 42
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
