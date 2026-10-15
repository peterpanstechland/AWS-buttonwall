import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PortGridTest(unittest.TestCase):
    def test_display_grid_is_four_by_four(self):
        hardware = json.loads((ROOT / "config" / "hardware.json").read_text(encoding="utf-8"))
        grid = hardware["display_grid"]
        self.assertEqual(len(grid), 4)
        slots = [slot for row in grid for slot in row]
        self.assertEqual(len(slots), 16)
        self.assertEqual(len(set(slots)), 16)
        self.assertTrue(all(len(row) == 4 for row in grid))
        panel_slots = {button["slot"] for button in hardware["buttons"] if button["slot"] != "START"}
        self.assertEqual(set(slots), panel_slots)
