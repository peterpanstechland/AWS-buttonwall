#pragma once

#include <stdint.h>

void strip_init(void);
void strip_fill(int lane, uint8_t r, uint8_t g, uint8_t b);
void strip_clear(void);
void strip_chase(int lane, int count, uint8_t r, uint8_t g, uint8_t b, int hot);
void strip_show(void);
/* Game panels use the existing, field-tested byte order and brightness cap. */
void strip_panel(int button_id, uint8_t r, uint8_t g, uint8_t b);
