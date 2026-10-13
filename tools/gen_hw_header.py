#!/usr/bin/env python3
"""Write firmware/main/generated_hw.h from config/hardware.json."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
hardware = json.loads((ROOT / "config" / "hardware.json").read_text(encoding="utf-8"))
lines = [
    "#pragma once",
    "#include <stdint.h>",
    f"#define HW_REVISION \"{hardware['revision']}\"",
    f"#define HW_PIXELS_PER_PANEL {hardware['led']['pixels_per_panel']}",
    f"#define HW_OE_GPIO {hardware['led']['oe_gpio']}",
    f"#define HW_BUTTON_COUNT {len(hardware['buttons'])}",
    f"#define HW_LANE_COUNT {len(hardware['led']['lanes'])}",
    "static const int HW_BUTTON_GPIO[HW_BUTTON_COUNT] = {",
]
lines.append("    " + ", ".join(str(button["gpio"]) for button in hardware["buttons"]))
lines.append("};")
lines.append("static const int HW_LANE_GPIO[HW_LANE_COUNT] = {")
lines.append("    " + ", ".join(str(lane["gpio"]) for lane in hardware["led"]["lanes"]))
lines.append("};")
bits = []
for button in hardware["buttons"]:
    if button["id"] == 0:
        bits.append("-1")
        continue
    lamp = hardware["lamps"]["bits"][button["slot"]]
    bits.append(str(lamp["bit"] + (8 if lamp["port"] == "B" else 0)))
lines.append("static const int8_t HW_LAMP_BIT[HW_BUTTON_COUNT] = {")
lines.append("    " + ", ".join(bits))
lines.append("};")
target = ROOT / "firmware" / "main" / "generated_hw.h"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(target)
