#!/usr/bin/env python3
"""Write firmware/main/generated_hw.h from config/hardware.json."""

import json
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
hardware = json.loads((ROOT / "config" / "hardware.json").read_text(encoding="utf-8"))
lines = [
    "#pragma once",
    "#include <stdint.h>",
    f"#define HW_REVISION \"{hardware['revision']}\"",
    f"#define HW_PIXELS_PER_PANEL {hardware['led']['pixels_per_panel']}",
    f"#define HW_OE_GPIO {hardware['led']['oe_gpio']}",
    f"#define HW_I2C_SDA_GPIO {hardware['lamps']['i2c_sda']}",
    f"#define HW_I2C_SCL_GPIO {hardware['lamps']['i2c_scl']}",
    f"#define HW_MCP23017_ADDR {hardware['lamps']['mcp23017_addr']}",
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
slot_lane = {}
for index, lane in enumerate(hardware["led"]["lanes"]):
    for slot in lane["slots"]:
        slot_lane[slot] = index
lanes = []
names = []
for button in hardware["buttons"]:
    names.append('"' + button["slot"] + '"')
    lanes.append(str(slot_lane.get(button["slot"], -1)))
lines.append("static const char *HW_BUTTON_NAME[HW_BUTTON_COUNT] = {")
lines.append("    " + ", ".join(names))
lines.append("};")
lines.append("static const int HW_BUTTON_LANE[HW_BUTTON_COUNT] = {")
lines.append("    " + ", ".join(lanes))
lines.append("};")
target = ROOT / "firmware" / "main" / "generated_hw.h"
mapping = {"buttons": [{k:b[k] for k in ('id','key','slot','gpio')} for b in hardware['buttons']],
           "lanes": [{k:l[k] for k in ('lane','gpio','slots')} for l in hardware['led']['lanes']],
           "pixels_per_panel": hardware['led']['pixels_per_panel'], "revision": hardware['revision']}
crc = zlib.crc32(json.dumps(mapping, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode()) & 0xffffffff
lines.append(f'#define HW_MAPPING_CRC {crc}u')
offsets = {slot:i*hardware['led']['pixels_per_panel'] for lane in hardware['led']['lanes'] for i,slot in enumerate(lane['slots'])}
lines.extend(['static const int HW_BUTTON_OFFSET[HW_BUTTON_COUNT] = {',
              '    ' + ', '.join(str(offsets.get(b['slot'], -1)) for b in hardware['buttons']), '};'])
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(target)
