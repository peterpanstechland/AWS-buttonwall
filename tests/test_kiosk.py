import unittest

from deploy.kiosk import output_modes, preferred_usb_sink


class KioskDisplayTests(unittest.TestCase):
    def test_usb_speaker_is_preferred_over_internal_codec_and_hdmi(self):
        sinks = [
            {"name": "internal", "properties": {"device.bus": "platform"}},
            {"name": "hdmi", "properties": {}},
            {"name": "speaker", "properties": {"device.bus": "usb"}},
        ]
        self.assertEqual(preferred_usb_sink(sinks)["name"], "speaker")
        self.assertIsNone(preferred_usb_sink(sinks[:2]))

    def test_x5_edid_skips_oversized_and_interlaced_modes(self):
        query = """Screen 0: minimum 320 x 200, current 2048 x 1152, maximum 4096 x 4096
HDMI-1 connected primary 2048x1152+0+0 (normal left inverted right x axis y axis)
   2048x1152     60.00*+
   1920x1200     59.88
   1920x1080     60.00 50.00
   1920x1080i    60.00 50.00
   1280x720      60.00
"""
        self.assertEqual(output_modes(query), {"HDMI-1": [(1920, 1080), (1280, 720)]})

    def test_small_panel_keeps_its_preferred_mode_first(self):
        query = """HDMI-A-1 connected 1280x800+0+0 (normal left inverted right x axis y axis)
   1280x800      60.00*+
   1920x1080     60.00
   1024x600      60.00
"""
        self.assertEqual(output_modes(query)["HDMI-A-1"][0], (1280, 800))

    def test_unconnected_non_hdmi_and_portrait_modes_are_ignored(self):
        query = """HDMI-1 disconnected (normal left inverted right x axis y axis)
DSI-1 connected 1080x1920+0+0 (normal left inverted right x axis y axis)
   1280x720      60.00
HDMI-2 connected (normal left inverted right x axis y axis)
   1080x1920     60.00
   1280x720i     60.00
   1280x720      60.00
"""
        self.assertEqual(output_modes(query), {"HDMI-2": [(1280, 720)]})


if __name__ == "__main__":
    unittest.main()
