#include "awg1.h"

#include <string.h>

uint32_t awg1_crc32(const uint8_t *data, size_t len)
{
    uint32_t crc = 0xFFFFFFFFu;
    for (size_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (int bit = 0; bit < 8; bit++) {
            uint32_t mask = -(crc & 1u);
            crc = (crc >> 1) ^ (0xEDB88320u & mask);
        }
    }
    return ~crc;
}

size_t awg1_encode(uint8_t *dst, size_t cap, uint8_t msg_type, uint32_t seq, bool ack, const char *json)
{
    size_t body = strlen(json);
    if (body > AWG1_MAX_PAYLOAD || cap < 16 + body) {
        return 0;
    }
    dst[0] = 0xA5;
    dst[1] = 0x5A;
    dst[2] = 1;
    dst[3] = msg_type;
    dst[4] = ack ? 1 : 0;
    dst[5] = 0;
    memcpy(dst + 6, &seq, 4);
    uint16_t stored = (uint16_t)body;
    memcpy(dst + 10, &stored, 2);
    memcpy(dst + 12, json, body);
    uint32_t crc = awg1_crc32(dst + 2, 10 + body);
    memcpy(dst + 12 + body, &crc, 4);
    return 16 + body;
}

static int magic_at(const uint8_t *buf, size_t len, size_t index)
{
    return index + 1 < len && buf[index] == 0xA5 && buf[index + 1] == 0x5A;
}

int awg1_try_parse(uint8_t *buf, size_t *len, awg1_view_t *view)
{
    size_t start = 0;
    while (start + 1 < *len && !magic_at(buf, *len, start)) {
        start++;
    }
    if (start) {
        memmove(buf, buf + start, *len - start);
        *len -= start;
    }
    if (*len < 12) {
        return 0;
    }
    uint16_t payload_len = 0;
    memcpy(&payload_len, buf + 10, 2);
    if (payload_len > AWG1_MAX_PAYLOAD) {
        memmove(buf, buf + 2, *len - 2);
        *len -= 2;
        return -1;
    }
    size_t total = 16u + payload_len;
    if (*len < total) {
        return 0;
    }
    uint32_t expect = 0;
    memcpy(&expect, buf + 12 + payload_len, 4);
    if (awg1_crc32(buf + 2, 10 + payload_len) != expect || buf[2] != 1) {
        memmove(buf, buf + 2, *len - 2);
        *len -= 2;
        return -1;
    }
    view->msg_type = buf[3];
    view->ack_required = buf[4] & 1;
    memcpy(&view->seq, buf + 6, 4);
    view->payload = buf + 12;
    view->payload_len = payload_len;
    return 1;
}
