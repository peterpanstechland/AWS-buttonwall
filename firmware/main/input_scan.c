#include "input_scan.h"

#include "driver/gpio.h"
#include "esp_timer.h"
#include "generated_hw.h"

#define DEBOUNCE_US 20000
#define QUEUE_LEN 64

typedef struct {
    bool stable_down;
    bool candidate_down;
    uint64_t candidate_since;
} key_t;

static key_t keys[HW_BUTTON_COUNT];
static input_event_t queue[QUEUE_LEN];
static int q_head;
static int q_tail;
static int q_count;

static void push(input_event_t event)
{
    if (q_count == QUEUE_LEN) {
        return;
    }
    queue[q_tail] = event;
    q_tail = (q_tail + 1) % QUEUE_LEN;
    q_count++;
}

void input_scan_init(void)
{
    gpio_config_t cfg = {
        .pin_bit_mask = 0,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    for (int i = 0; i < HW_BUTTON_COUNT; i++) {
        cfg.pin_bit_mask |= 1ULL << HW_BUTTON_GPIO[i];
    }
    gpio_config(&cfg);
    gpio_config_t oe = {
        .pin_bit_mask = 1ULL << HW_OE_GPIO,
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&oe);
    gpio_set_level(HW_OE_GPIO, 1);
}

void input_scan_tick(uint64_t now_us)
{
    for (int i = 0; i < HW_BUTTON_COUNT; i++) {
        bool down = gpio_get_level(HW_BUTTON_GPIO[i]) == 0;
        key_t *key = &keys[i];
        if (down != key->candidate_down) {
            key->candidate_down = down;
            key->candidate_since = now_us;
        }
        if (down != key->stable_down && now_us - key->candidate_since >= DEBOUNCE_US) {
            key->stable_down = down;
            input_event_t event = {
                .button_id = (uint8_t)i,
                .raw_us = key->candidate_since,
                .confirmed_us = now_us,
                .down = down,
            };
            push(event);
        }
    }
}

bool input_pop(input_event_t *out)
{
    if (q_count == 0) {
        return false;
    }
    *out = queue[q_head];
    q_head = (q_head + 1) % QUEUE_LEN;
    q_count--;
    return true;
}

bool input_any_down(void)
{
    for (int i = 0; i < HW_BUTTON_COUNT; i++) {
        if (keys[i].stable_down) {
            return true;
        }
    }
    return false;
}
