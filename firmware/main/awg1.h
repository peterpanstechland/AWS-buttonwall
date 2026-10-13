#pragma once

#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

#define AWG1_MAX_PAYLOAD 2048

typedef struct {
    uint8_t msg_type;
    uint32_t seq;
    bool ack_required;
    const uint8_t *payload;
    uint16_t payload_len;
} awg1_view_t;

uint32_t awg1_crc32(const uint8_t *data, size_t len);
size_t awg1_encode(uint8_t *dst, size_t cap, uint8_t msg_type, uint32_t seq, bool ack, const char *json);

/* Returns 1 when a full valid frame is at the front of buf and consumed into view.
   Returns 0 if more bytes are needed. Returns -1 after dropping a bad prefix. */
int awg1_try_parse(uint8_t *buf, size_t *len, awg1_view_t *view);
