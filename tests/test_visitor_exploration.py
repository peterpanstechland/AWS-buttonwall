import unittest
from collections import Counter

from reference.catalog import load_missions, load_services
from reference.rules import analyze_selection, frontier
from wall_backend.engine import Engine
from wall_backend.graph import project_graph
from wall_backend.store import Store


class VisitorExplorationTests(unittest.TestCase):
    def test_every_service_supports_two_instances_and_undo(self):
        self.start('FREE')
        for service in self.e.services:
            if not service['id']:
                continue
            for expected in (1, 2, 0):
                self.now += 100_000
                self.e.sim_click(service['id'])
                self.assertEqual(self.e.selected[service['key']], expected)
            self.e.undo()
            self.assertEqual(self.e.selected[service['key']], 2)
            self.now += 100_000
            self.e.sim_click(service['id'])
            self.assertEqual(self.e.selected[service['key']], 0)

    def setUp(self):
        self.now = 5_000_000
        self.e = Engine(Store(), clock_us=lambda: self.now)
        self.e.cfg['pre_countdown_ms'] = 0
        self.e.tick()

    def tearDown(self):
        self.e.store.conn.close()

    def start(self, mode='GUIDED', mission=None):
        if self.e.state == 'IDLE':
            self.e._gesture('CLICK')
        self.e.select_mode(mode)
        self.e.start(mission)

    def test_third_exit_blocks_fourth_and_waits_for_handoff(self):
        for n in range(1, 4):
            self.start('FREE')
            self.assertEqual(self.e.visit_plays, n)
            self.e.leave()
        self.assertEqual(self.e.state, 'VISIT_DONE')
        for action in ('CLICK', 'DOUBLE', 'HOLD'):
            self.e._gesture(action)
            self.e.start()
            self.e.home()
            self.assertEqual(self.e.state, 'VISIT_DONE')
        self.now += 4_999_000
        self.e.tick()
        self.assertEqual(self.e.state, 'VISIT_DONE')
        self.now += 1_000
        self.e.tick()
        self.assertEqual(self.e.state, 'IDLE')
        self.assertEqual(self.e.visit_plays, 0)

    def test_home_settings_and_mode_change_do_not_refill_plays(self):
        self.start('FREE')
        self.e.home()
        self.e.open_settings()
        self.e.close_settings()
        self.start('GUIDED', 'M01_VOICE')
        self.assertEqual(self.e.visit_plays, 2)

    def test_random_draws_do_not_repeat_in_visit(self):
        chosen = []
        for _ in range(3):
            self.start()
            chosen.append(self.e.mission_id)
            self.e.leave()
        self.assertEqual(len(set(chosen)), 3)

    def test_failed_third_run_cannot_retry(self):
        self.e.visit_plays = 2
        self.start('GUIDED', 'M01_VOICE')
        self.e.sim_click(1)
        self.assertEqual(self.e.state, 'RESULT')
        self.assertEqual(self.e.snapshot()['visit_remaining'], 0)
        self.e._gesture('CLICK')
        self.assertEqual(self.e.state, 'VISIT_DONE')

    def test_mashing_does_not_validate_any_workflow(self):
        selected = Counter({s['key']: 1 for s in load_services()[0] if s['id']})
        result = analyze_selection(load_missions(), selected)
        self.assertTrue(result['candidates'])
        for c in result['candidates']:
            self.assertEqual(c['status'], 'VALID_PARTIAL')
            self.assertTrue(c['extra'])
            graph = project_graph(self.e.missions[c['mission_id']], set(), selected)
            self.assertNotEqual(graph['status'], 'complete')

    def test_new_examples_are_complete_and_playable(self):
        for mission in load_missions():
            if not mission.get('sources'):
                continue
            selected = Counter(n['service'] for n in mission['nodes'] if n['required'])
            result = analyze_selection(load_missions(), selected)
            match = next(c for c in result['candidates'] if c['mission_id'] == mission['id'])
            self.assertEqual(match['status'], 'VALID_COMPLETE')
            done = set()
            while len(done) < len(mission['nodes']):
                ready = frontier(mission, done)
                self.assertTrue(ready)
                done.update(n['node_id'] for n in ready)
            self.assertEqual(project_graph(mission, done)['status'], 'complete')

    def test_unknown_combination_is_not_a_failure(self):
        self.start('FREE')
        self.e.selected = Counter(EC2=1, POLLY=1, SQS=1)
        self.assertEqual(self.e.analyze()['status'], 'UNSUPPORTED')
        self.assertIsNone(self.e.failure)
        self.assertEqual(self.e.state, 'ACTIVE')

    def test_free_time_cannot_be_extended_by_repeated_input(self):
        self.start('FREE')
        for _ in range(120):
            self.now += 1_000_000
            self.e.analyze()
            self.e.tick()
        self.assertEqual(self.e.state, 'RESULT')
        self.assertEqual(self.e.notice, 'FREE_TIME_UP')
        self.assertEqual(self.e.snapshot()['remaining_ms'], 0)

    def test_completed_result_allows_time_and_physical_replay(self):
        self.start('FREE')
        self.e.selected = Counter(IOT_CORE=1, DYNAMODB=1)
        self.e.analyze()
        self.e.confirm_candidate('M10_IOT_DIRECT')
        self.assertEqual(self.e.state, 'RESULT')
        self.assertEqual(self.e.snapshot()['idle_return_remaining_ms'], 60000)
        cells = self.e.navigation()['cells']
        self.assertEqual(next(c['action'] for c in cells if c['slot']=='B2'), 'replay')
        revision = self.e.ui_settings['replay_seq']
        self.now += 100_000
        self.e.sim_click(6)
        self.assertEqual(self.e.ui_settings['replay_seq'], revision + 1)
        self.assertEqual(self.e.state, 'RESULT')
        self.assertEqual(self.e.visit_plays, 1)

