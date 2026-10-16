import json,re,unittest
from pathlib import Path
from wall_backend.engine import Engine
from wall_backend.store import Store
from reference.catalog import load_hardware

class KiroLayoutTests(unittest.TestCase):
 def test_serial_chains_have_exact_non_overlapping_pixels(self):
  h=load_hardware();n=h['led']['pixels_per_panel'];self.assertEqual(n,31)
  lanes=h['led']['lanes'];self.assertEqual([len(l['slots'])*n for l in lanes],[124,124,124,155])
  self.assertEqual(lanes[3]['slots'],['D1','D2','D3','D4','START'])
  self.assertEqual(sum(len(l['slots'])*n for l in lanes),527)
  slots=[s for l in lanes for s in l['slots']];self.assertEqual(len(set(slots)),17)
  header=Path('firmware/main/generated_hw.h').read_text()
  def values(name):return [int(x) for x in re.search(name+r'\[[^\]]+\]\s*=\s*\{([^}]+)',header,re.S)[1].split(',')]
  self.assertEqual(values('HW_LANE_PIXELS'),[124,124,124,155])
  self.assertEqual(values('HW_BUTTON_OFFSET')[0],124)
  self.assertEqual(values('HW_BUTTON_LANE')[0],3)
  self.assertEqual(values('HW_BUTTON_OFFSET')[16],93)
 def test_purple_kiro_state_guidance(self):
  e=Engine(Store());self.addCleanup(e.store.conn.close)
  for state,effect in [('IDLE','breathe'),('MODE_LOBBY','breathe'),('MISSION_SELECT','breathe'),('SETTINGS','breathe'),('COUNTDOWN','pulse'),('ACTIVE','steady'),('RESULT','pulse'),('VISIT_DONE','breathe')]:
   e.state=state;k=e.light_plan({'cells':[]})['kiro']
   self.assertEqual(k['effect'],effect,state);self.assertEqual(k['color'],[160,64,255])
