idf_component_register(
    SRCS "app_main.c" "awg1.c" "input_scan.c" "strip_engine.c"
    INCLUDE_DIRS "."
    REQUIRES driver esp_timer nvs_flash
)
