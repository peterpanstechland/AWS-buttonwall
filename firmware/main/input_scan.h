#pragma once

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    uint8_t button_id;
    uint64_t raw_us;
    uint64_t confirmed_us;
    bool down;
} input_event_t;

void input_scan_init(void);
void input_scan_tick(uint64_t now_us);
bool input_pop(input_event_t *out);
bool input_any_down(void);
