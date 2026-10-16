import sqlite3,tempfile,unittest
from pathlib import Path
from wall_backend.store import Store
from wall_backend.engine import Engine
class WelcomeReminderTests(unittest.TestCase):
 def test_old_database_migrates_and_toggle_survives_restart(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'wall.db';c=sqlite3.connect(path)
   c.execute('CREATE TABLE ui_preferences (singleton INTEGER PRIMARY KEY,language TEXT,voice_enabled INTEGER,volume INTEGER,reduced_motion INTEGER,revision INTEGER,replay_seq INTEGER)')
   c.execute("INSERT INTO ui_preferences VALUES (1,'en',1,40,0,7,2)");c.commit();c.close()
   store=Store(path);e=Engine(store);self.assertTrue(e.ui_settings['welcome_reminder']);self.assertEqual(e.ui_settings['volume'],40)
   e.open_settings();cell=next(c for c in e.navigation()['cells'] if c['slot']=='B4')
   self.assertEqual(cell['key'],'SQS');e.sim_click(cell['button_id'])
   self.assertFalse(e.ui_settings['welcome_reminder']);self.assertTrue(e.ui_settings['voice_enabled'])
   store.conn.close();store=Store(path)
   self.assertFalse(store.ui_settings()['welcome_reminder']);self.assertEqual(store.ui_settings()['language'],'en');store.conn.close()
 def test_setting_accepts_boolean_only_and_settings_context(self):
  store=Store();self.addCleanup(store.conn.close);e=Engine(store)
  with self.assertRaises(RuntimeError):e.update_ui_settings({'welcome_reminder':False})
  e.open_settings()
  with self.assertRaises(ValueError):e.update_ui_settings({'welcome_reminder':'false'})
