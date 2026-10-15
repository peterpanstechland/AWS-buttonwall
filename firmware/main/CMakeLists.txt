idf_component_register(
    SRCS "app_main.c" "awg1.c" "bringup.c" "input_scan.c" "strip_engine.c"
    INCLUDE_DIRS "."
    REQUIRES driver esp_driver_i2c esp_driver_usb_serial_jtag esp_timer nvs_flash
)
