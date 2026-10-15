#include "bringup.h"

#include "generated_hw.h"
#include "input_scan.h"
#include "strip_engine.h"

#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "esp_timer.h"

#include <ctype.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#define CHASE_US 100000

static i2c_master_dev_handle_t mcp;
static bool lamp_ok;
static int active = -1;
static int chase;
static uint64_t next_chase;
static char line[64];
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

static void lamp_init(void)
{
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
        .scl_speed_hz = 100000,
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
}

static void lamp_apply(void)
{
    uint16_t mask = 0;
    if (lamp_ok && active > 0 && HW_LAMP_BIT[active] >= 0) {
        mask = (uint16_t)(1u << HW_LAMP_BIT[active]);
    }
    if (!lamp_ok) {
        return;
    }
    mcp_write(0x14, (uint8_t)(mask & 0xFF));
    mcp_write(0x15, (uint8_t)(mask >> 8));
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
    lamp_apply();
    show_active();
}

static void handle(char *text)
{
    while (*text == ' ') {
        text++;
    }
    if (strncmp(text, "BW ", 3) == 0) {
        text += 3;
    }
    if (strncmp(text, "PING", 4) == 0) {
        printf("BW PONG %s\n", HW_REVISION);
        return;
    }
    if (strncmp(text, "OFF", 3) == 0) {
        select_slot(-1);
        printf("BW OK OFF\n");
        return;
    }
    if (strncmp(text, "SLOT ", 5) == 0) {
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
    int flags = fcntl(fileno(stdin), F_GETFL, 0);
    if (flags >= 0) {
        fcntl(fileno(stdin), F_SETFL, flags | O_NONBLOCK);
    }
    setvbuf(stdout, NULL, _IONBF, 0);
    lamp_init();
    printf("BW PONG %s\n", HW_REVISION);
}

void bringup_poll(uint64_t now_us)
{
    unsigned char ch;
    while (read(STDIN_FILENO, &ch, 1) == 1) {
        if (ch == '\n' || ch == '\r') {
            if (line_len > 0) {
                line[line_len] = 0;
                handle(line);
                line_len = 0;
            }
            continue;
        }
        if (line_len < (int)sizeof line - 1) {
            line[line_len++] = (char)ch;
        }
    }

    input_event_t event;
    while (input_pop(&event)) {
        if (event.button_id < HW_BUTTON_COUNT) {
            printf("BW BTN %s %s\n", HW_BUTTON_NAME[event.button_id], event.down ? "DOWN" : "UP");
        }
    }

    if (active > 0 && now_us >= next_chase) {
        chase = (chase + 1) % HW_PIXELS_PER_PANEL;
        next_chase = now_us + CHASE_US;
        show_active();
    }
}
