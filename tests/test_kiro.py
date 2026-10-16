"""Wall keys choose menu entries; Kiro confirms with debounced physical edges."""
import unittest
from reference.rules import frontier
from wall_backend.engine import Engine
from wall_backend.store import Store


class KiroTests(unittest.TestCase):
    def setUp(self):
        self.now = 5_000_000
        self.engine = Engine(Store(), clock_us=lambda: self.now)
        self.engine.cfg['pre_countdown_ms'] = 0
        self.engine.mcu.cfg['pre_countdown_ms'] = 0
        self.engine.tick()

    def advance(self, us):
        self.now += us
        self.engine.tick()

    def edge(self, down):
        self.engine.sim_level(0, down)
        self.advance(25_000)

    def gesture(self, kind):
        self.edge(True)
        if kind == 'HOLD':
            self.advance(2_000_000)
        self.edge(False)
        if kind == 'DOUBLE':
            self.advance(60_000)
            self.edge(True)
            self.edge(False)
        self.advance(350_000)

    def enter(self, mode):
        self.gesture('CLICK')
        self.service({'GUIDED': 'EC2', 'RUSH60_RANKED': 'S3', 'FREE': 'API_GATEWAY'}[mode])
        self.gesture('CLICK')
        if mode == 'GUIDED':
            self.assertEqual(self.engine.state, 'MISSION_SELECT')
            self.gesture('CLICK')
        self.assertEqual(self.engine.state, 'ACTIVE')

    def service(self, key):
        self.engine.sim_click(self.engine.by_key[key]['id'])
        self.advance(100_000)

    def test_menu_double_does_not_also_cycle_and_hold_does_not_click(self):
        self.gesture('CLICK')
        self.assertEqual(self.engine.mode, 'GUIDED')
        self.gesture('DOUBLE')
        self.assertEqual(self.engine.state, 'MISSION_SELECT')
        self.assertIsNone(self.engine.snapshot()['menu_mission_id'])
        self.service('S3')
        self.assertEqual(self.engine.snapshot()['menu_mission_id'], 'M02_VISION')
        self.gesture('HOLD')
        self.assertEqual(self.engine.state, 'MODE_LOBBY')
        self.assertEqual(self.engine.mode, 'GUIDED')
        self.gesture('HOLD')
        self.assertEqual(self.engine.state, 'IDLE')

    def test_guided_complete_next_and_pause_with_one_key(self):
        self.enter('GUIDED')
        self.gesture('CLICK')
        self.assertTrue(self.engine.paused)
        self.advance(20_000_000)
        self.assertIsNone(self.engine.failure)
        self.gesture('CLICK')
        self.assertFalse(self.engine.paused)
        while self.engine.state == 'ACTIVE':
            node = next(n for n in frontier(self.engine.missions[self.engine.mission_id], self.engine.done) if n['required'])
            self.service(node['service'])
        self.assertEqual(self.engine.snapshot()['graph']['status'], 'complete')
        self.gesture('CLICK')
        self.assertNotEqual(self.engine.mission_id, 'M01_VOICE')
        self.assertIn(self.engine.mission_id, self.engine.missions)
        self.assertEqual(self.engine.state, 'ACTIVE')
        self.gesture('HOLD')
        self.assertEqual(self.engine.state, 'MODE_LOBBY')

    def test_failure_retry_and_back_to_modes(self):
        self.enter('GUIDED')
        self.service('POLLY')
        self.assertEqual(self.engine.failure['reason'], 'WRONG_SERVICE')
        self.gesture('CLICK')
        self.assertEqual(self.engine.state, 'ACTIVE')
        self.assertIsNone(self.engine.failure)
        self.service('POLLY')
        self.gesture('DOUBLE')
        self.assertEqual(self.engine.state, 'MODE_LOBBY')

    def test_free_repeat_instances_undo_analysis_and_confirm(self):
        self.enter('FREE')
        self.service('LAMBDA')
        self.service('LAMBDA')
        self.assertEqual(self.engine.selected['LAMBDA'], 2)
        self.service('LAMBDA')
        self.assertEqual(self.engine.selected['LAMBDA'], 0)
        self.gesture('DOUBLE')
        self.assertEqual(self.engine.selected['LAMBDA'], 2)
        self.service('API_GATEWAY'); self.service('SQS'); self.service('DYNAMODB')
        self.gesture('CLICK')
        self.assertTrue(self.engine.free_review)
        self.gesture('HOLD')
        self.assertFalse(self.engine.free_review)
        self.assertEqual(self.engine.state, 'ACTIVE')
        self.gesture('CLICK')
        for _ in range(len(self.engine.candidates)):
            if self.engine.snapshot()['focused_candidate_id'] == 'M07_EVENT_DRIVEN':
                break
            self.gesture('CLICK')
        self.assertEqual(self.engine.snapshot()['focused_candidate_id'], 'M07_EVENT_DRIVEN')
        self.gesture('DOUBLE')
        self.assertEqual(self.engine.state, 'RESULT')
        self.assertEqual(self.engine.snapshot()['graph']['status'], 'complete')
        self.assertEqual(self.engine.solutions, 1)

    def test_rush_forfeit_requires_confirm_and_does_not_pause(self):
        self.enter('RUSH60_RANKED')
        remaining = self.engine.snapshot()['remaining_ms']
        self.gesture('HOLD')
        self.assertTrue(self.engine.forfeit_pending)
        self.assertLess(self.engine.snapshot()['remaining_ms'], remaining)
        self.gesture('CLICK')
        self.assertFalse(self.engine.forfeit_pending)
        self.gesture('HOLD')
        self.gesture('DOUBLE')
        self.assertEqual(self.engine.state, 'INTERRUPTED')
        self.assertEqual(self.engine.leaderboard(), [])

    def test_practice_can_return_to_supported_lobby_modes(self):
        self.engine.state = 'MODE_LOBBY'
        self.engine.mode = 'RUSH60_PRACTICE'
        self.service('EC2')
        self.assertEqual(self.engine.mode, 'GUIDED')
        self.assertEqual(self.engine.state, 'MODE_LOBBY')


if __name__ == '__main__':
    unittest.main()
