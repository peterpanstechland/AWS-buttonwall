#include "bringup.h"

#include "generated_hw.h"
#include "input_scan.h"
#include "strip_engine.h"

#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "esp_rom_sys.h"
#include "esp_timer.h"
#include "esp_random.h"
#include <inttypes.h>
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "hal/usb_serial_jtag_ll.h"

#include <ctype.h>
#include <stdio.h>
#include <string.h>

#define CHASE_US 100000
#define PERIOD_US 5000
#define BREATH_US 2000000

static i2c_master_dev_handle_t mcp;
static SemaphoreHandle_t lamp_lock;
static bool lamp_ok;
static volatile uint32_t lamp_target;
static uint16_t lamp_shadow = 0xFFFF;
static int active = -1;
static int chase;
static uint64_t next_chase;
static char line[256];
static bool line_overflow;
static volatile bool game_mode;
static uint32_t boot_id, state_seq, button_mask;
static uint64_t last_host, next_state, next_render;
static uint8_t scene[17][4];
static volatile uint32_t game_lamp_mask;
static int line_len;

static const uint8_t LANE_COLOR[HW_LANE_COUNT][3] = {
    {255, 0, 0},
    {0, 255, 0},
    {0, 0, 255},
    {255, 180, 0},
};

static bool mcp_write(uint8_t reg, uint8_t value)
{
    uint8_t buf[2] = {reg, value};
    return i2c_master_transmit(mcp, buf, sizeof buf, 100) == ESP_OK;
}

static void lamp_task(void *arg);

static void lamp_init(void)
{
    lamp_lock = xSemaphoreCreateMutex();
    i2c_master_bus_handle_t bus;
    i2c_master_bus_config_t bus_cfg = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = HW_I2C_SDA_GPIO,
        .scl_io_num = HW_I2C_SCL_GPIO,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    i2c_device_config_t dev_cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = HW_MCP23017_ADDR,
        .scl_speed_hz = 400000,
    };
    if (i2c_new_master_bus(&bus_cfg, &bus) != ESP_OK) {
        return;
    }
    if (i2c_master_bus_add_device(bus, &dev_cfg, &mcp) != ESP_OK) {
        return;
    }
    /* Output latch low before the pins become outputs, so lamps stay off. */
    if (!mcp_write(0x0A, 0x00) || !mcp_write(0x14, 0x00) || !mcp_write(0x15, 0x00) ||
        !mcp_write(0x00, 0x00) || !mcp_write(0x01, 0x00)) {
        return;
    }
    lamp_ok = true;
    xTaskCreate(lamp_task, "lamp", 3072, NULL, 1, NULL);
}

static void lamp_write(uint16_t mask)
{
    if (!lamp_ok) {
        return;
    }
    xSemaphoreTake(lamp_lock, portMAX_DELAY);
    if (mask != lamp_shadow) {
        uint8_t lo = (uint8_t)(mask & 0xFF);
        uint8_t hi = (uint8_t)(mask >> 8);
        if ((uint8_t)(lamp_shadow & 0xFF) != lo) {
            mcp_write(0x14, lo);
        }
        if ((uint8_t)(lamp_shadow >> 8) != hi) {
            mcp_write(0x15, hi);
        }
        lamp_shadow = mask;
    }
    xSemaphoreGive(lamp_lock);
}

static uint32_t breath_on_us(uint64_t now_us)
{
    uint32_t breath = (uint32_t)(now_us % BREATH_US);
    uint32_t half = BREATH_US / 2;
    uint32_t tri = breath < half ? breath : (BREATH_US - breath);
    uint32_t on = tri * (PERIOD_US - 800) / half;
    if (on > 0 && on < 500) {
        on = 500;
    }
    return on;
}

static void lamp_task(void *arg)
{
    (void)arg;
    uint64_t last_yield = 0;
    while (true) {
        if (game_mode) {
            lamp_write((uint16_t)game_lamp_mask);
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        uint32_t target = lamp_target;
        if (target == 0) {
            lamp_write(0);
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }
        uint64_t now = esp_timer_get_time();
        uint32_t on_us = breath_on_us(now);
        if (on_us == 0) {
            lamp_write(0);
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        if (on_us >= PERIOD_US - 400) {
            lamp_write((uint16_t)target);
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        uint32_t phase = (uint32_t)(now % PERIOD_US);
        bool on = phase < on_us;
        lamp_write(on ? (uint16_t)target : 0);
        uint32_t edge = on ? on_us : PERIOD_US;
        uint32_t wait = edge > phase ? edge - phase : 100;
        if (wait < 100) {
            wait = 100;
        } else if (wait > 400) {
            wait = 400;
        }
        esp_rom_delay_us(wait);
        /* taskYIELD does not schedule lower-priority IDLE at 100 Hz. */
        if (now - last_yield >= 20000) { last_yield = now; vTaskDelay(1); }
        else taskYIELD();
    }
}

static void lamp_set_target(void)
{
    lamp_target = 0;
    if (active > 0 && HW_LAMP_BIT[active] >= 0) {
        lamp_target = (uint32_t)(1u << HW_LAMP_BIT[active]);
    }
    lamp_write(0);
}

static void show_active(void)
{
    strip_clear();
    if (active > 0) {
        int lane = HW_BUTTON_LANE[active];
        gpio_set_level(HW_OE_GPIO, 0);
        strip_chase(lane, HW_PIXELS_PER_PANEL, LANE_COLOR[lane][0], LANE_COLOR[lane][1], LANE_COLOR[lane][2], chase);
        strip_show();
        return;
    }
    gpio_set_level(HW_OE_GPIO, 0);
    strip_show();
    gpio_set_level(HW_OE_GPIO, 1);
}

static int find_slot(const char *text)
{
    char name[8];
    int n = 0;
    while (text[n] && text[n] != ' ' && text[n] != '\r' && n < 7) {
        name[n] = (char)toupper((unsigned char)text[n]);
        n++;
    }
    name[n] = 0;
    if (n == 0) {
        return -1;
    }
    for (int i = 0; i < HW_BUTTON_COUNT; i++) {
        if (strcmp(name, HW_BUTTON_NAME[i]) == 0) {
            return i;
        }
    }
    return -1;
}

static void select_slot(int id)
{
    active = id;
    chase = 0;
    next_chase = esp_timer_get_time() + CHASE_US;
    lamp_set_target();
    show_active();
}

static void send_state(uint64_t now)
{
    printf("BW STATE %" PRIu32 " %" PRIu32 " %" PRIu64 " %" PRIu32 "\n",
           boot_id, ++state_seq, now, button_mask);
}

static void game_off(void)
{
    game_mode = false;
    game_lamp_mask = 0;
    memset(scene, 0, sizeof scene);
    select_slot(-1);
}

static void render_game(uint64_t now)
{
    strip_clear();
    uint32_t lamps = 0;
    uint32_t phase = (now / 1000) % 2000;
    unsigned breath = phase < 1000 ? phase * 255 / 1000 : (2000-phase) * 255 / 1000;
    for (int i=0; i<17; i++) {
        unsigned gain = scene[i][3] == 1 ? 255 : scene[i][3] == 2 ? ((now / 250000)%2 ? 40 : 255) : scene[i][3] == 3 ? breath : 0;
        int button_id = i == 16 ? 0 : i+1;
        strip_panel(button_id, scene[i][0]*gain/255, scene[i][1]*gain/255, scene[i][2]*gain/255);
        if (gain > 100 && HW_LAMP_BIT[button_id] >= 0) lamps |= 1u << HW_LAMP_BIT[button_id];
    }
    game_lamp_mask = lamps;
    gpio_set_level(HW_OE_GPIO, 0);
    strip_show();
}

static void handle(char *text)
{
    while (*text == ' ') {
        text++;
    }
    if (strncmp(text, "BW ", 3) == 0) {
        text += 3;
    }
    unsigned crc;
    int used = 0;
    if (sscanf(text, "GAME 3 %u%n", &crc, &used) == 1 && text[used] == 0) {
        if (crc != HW_MAPPING_CRC) { printf("BW ERR MAP\n"); return; }
        game_off(); game_mode = true; last_host = esp_timer_get_time();
        state_seq = 0; next_state = last_host; next_render = last_host;
        printf("BW HELLO 3 %" PRIu32 " %" PRIu32 " %" PRIu64 " %" PRIu32 "\n", boot_id, (uint32_t)HW_MAPPING_CRC, last_host, button_mask);
        return;
    }
    if (strcmp(text, "KEEP") == 0 && game_mode) { last_host = esp_timer_get_time(); return; }
    if (strncmp(text, "FRAME ", 6) == 0 && game_mode) {
        unsigned seq; char hex[137]; int end = 0;
        if (sscanf(text, "FRAME %u %136s%n", &seq, hex, &end) != 2 || text[end] || strlen(hex)!=136) { printf("BW ERR FRAME\n"); return; }
        uint8_t staged[17][4];
        for (int i=0;i<68;i++) {
            char pair[3] = {hex[i*2],hex[i*2+1],0}; unsigned value;
            if (!isxdigit((unsigned char)pair[0]) || !isxdigit((unsigned char)pair[1]) || sscanf(pair,"%2x",&value)!=1) { printf("BW ERR FRAME\n"); return; }
            staged[i/4][i%4] = value;
        }
        for (int i=0;i<17;i++) if(staged[i][3]>3) { printf("BW ERR EFFECT\n"); return; }
        memcpy(scene, staged, sizeof scene); last_host=esp_timer_get_time();
        render_game(last_host);
        printf("BW FRAME_OK %u %d\n",seq,lamp_ok ? 1 : 0);
        return;
    }
    if (strncmp(text, "PING", 4) == 0) {
        printf("BW PONG %s\n", HW_REVISION);
        return;
    }
    if (strncmp(text, "OFF", 3) == 0) {
        game_off();
        printf("BW OK OFF\n");
        return;
    }
    if (strncmp(text, "SLOT ", 5) == 0) {
        if (game_mode) { printf("BW ERR MODE\n"); return; }
        int id = find_slot(text + 5);
        if (id < 0) {
            printf("BW ERR SLOT\n");
            return;
        }
        select_slot(id);
        if (id > 0 && !lamp_ok) {
            printf("BW ERR LAMP\n");
        }
        printf("BW OK SLOT %s\n", HW_BUTTON_NAME[id]);
    }
}

void bringup_init(void)
{
    boot_id = esp_random();
    setvbuf(stdout, NULL, _IONBF, 0);
    lamp_init();
    printf("BW PONG %s\n", HW_REVISION);
}

void bringup_poll(uint64_t now_us)
{
    uint8_t ch;
    while (usb_serial_jtag_ll_read_rxfifo(&ch, 1) == 1) {
        if (ch == '\n' || ch == '\r') {
            if (line_len > 0 && !line_overflow) {
                line[line_len] = 0;
                handle(line);
                line_len = 0;
            }
            line_len = 0; line_overflow = false;
            continue;
        }
        if (line_len < (int)sizeof line - 1) {
            line[line_len++] = (char)ch;
        } else { line_overflow = true; }
    }

    /* Command handlers use a fresh clock; do not subtract it from stale poll time. */
    now_us = esp_timer_get_time();
    input_event_t event;
    while (input_pop(&event)) {
        if (event.button_id < HW_BUTTON_COUNT) {
            if (event.down) button_mask |= 1u << event.button_id;
            else button_mask &= ~(1u << event.button_id);
            if (game_mode) { send_state(now_us); continue; }
            printf("BW BTN %s %s\n", HW_BUTTON_NAME[event.button_id], event.down ? "DOWN" : "UP");
            if (event.down && event.button_id == active) {
                select_slot(-1);
                printf("BW OK OFF\n");
            }
        }
    }

    if (game_mode) {
        if (now_us - last_host > 2000000) { game_off(); printf("BW ERR WATCHDOG\n"); return; }
        if (now_us >= next_state) { send_state(now_us); next_state=now_us+100000; }
        if (now_us >= next_render) { render_game(now_us); next_render=now_us+50000; }
        return;
    }
    if (active > 0 && now_us >= next_chase) {
        chase = (chase + 1) % HW_PIXELS_PER_PANEL;
        next_chase = now_us + CHASE_US;
        show_active();
    }
}
