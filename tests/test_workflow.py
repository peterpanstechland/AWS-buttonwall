"""Gameplay boundary tests and graph projection tests for the construction screen."""
import unittest
from collections import Counter
from copy import deepcopy

from reference.awg1 import Frame, TIMER_EVENT
from reference.catalog import load_missions, load_game_config, pack_hash
from reference.rules import frontier
from wall_backend.engine import Engine
from wall_backend.graph import CONTENT, project_graph
from wall_backend.store import Store


class WorkflowTests(unittest.TestCase):
    def engine(self, mode='GUIDED', mission='M01_VOICE'):
        self.time = 5_000_000
        engine = Engine(Store(), clock_us=lambda: self.time)
        engine.mcu.cfg['pre_countdown_ms'] = 0
        engine.cfg['pre_countdown_ms'] = 0
        engine.state = 'MODE_LOBBY'
        engine.mode = mode
        return engine, lambda: engine.start(mission)

    def hit(self, engine, button):
        engine.sim_click(button)
        self.time += 100_000

    def test_one_press_lights_one_role_and_its_live_edges(self):
        engine, start = self.engine(); start()
        self.hit(engine, 13)
        graph = engine.snapshot()['graph']
        self.assertEqual([n['node_id'] for n in graph['nodes'] if n['state']=='live'], ['speech_to_text'])
        live = [e for e in graph['edges'] if e['state']=='live']
        self.assertEqual([(e['source'], e['target']) for e in live], [('input','speech_to_text')])
        self.assertEqual(graph['status'], 'building')
        self.hit(engine, 3)
        self.assertEqual(engine.snapshot()['graph']['connected_count'], 2)

    def test_wrong_hit_collapses_once_retains_progress_and_cannot_reopen(self):
        engine, start = self.engine(); start()
        self.hit(engine, 13); self.hit(engine, 14)
        self.assertEqual(engine.failure['reason'], 'WRONG_SERVICE')
        self.assertEqual(engine.failure['wrong_service'], 'POLLY')
        self.assertEqual(engine.score(), 50)
        self.assertEqual(engine.snapshot()['graph']['status'], 'collapsed')
        self.assertEqual(engine.snapshot()['graph']['connected_count'], 1)
        before=engine.snapshot()['step_remaining_ms']
        self.hit(engine, 3)
        self.time += 20_000_000
        engine.on_frame(Frame(TIMER_EVENT, {'event':'GO','t0_us':self.time}, 1, False, False))
        engine.tick()
        self.assertEqual(engine.state, 'RESULT')
        self.assertEqual(engine.score(), 50)
        self.assertEqual(engine.snapshot()['step_remaining_ms'], before)
        self.assertEqual(engine.store.conn.execute('SELECT count(*) FROM sessions').fetchone()[0], 1)
        self.assertEqual(engine.leaderboard(), [])
        self.assertEqual(engine.store.conn.execute("SELECT count(*) FROM audit WHERE action='workflow_collapsed'").fetchone()[0], 1)

    def test_step_timeout_does_not_require_a_browser(self):
        engine, start = self.engine(); start()
        self.time = engine.step_deadline_us + engine.cfg['debounce_us']
        engine.tick()
        self.assertEqual(engine.failure['reason'], 'STEP_TIMEOUT')
        self.assertEqual(engine.state, 'RESULT')

    def test_before_step_deadline_late_debounce_is_accepted(self):
        engine, start = self.engine(); start()
        raw = engine.step_deadline_us - 5_000
        engine.mcu.levels[13] = True; engine.mcu.scan(raw)
        self.time = raw + 20_000
        engine.tick()
        self.assertIsNone(engine.failure)
        self.assertEqual(engine.score(), 100)
        self.assertGreater(engine.step_deadline_us, self.time)

    def test_at_step_deadline_is_rejected(self):
        engine, start = self.engine(); start()
        self.time = engine.step_deadline_us
        self.hit(engine,13)
        self.assertEqual(engine.failure['reason'], 'STEP_TIMEOUT')
        self.assertEqual(engine.score(), 0)

    def test_round_timeout_collapses_after_input_drain(self):
        engine, start = self.engine('RUSH60_RANKED')
        engine.cfg['collapse']['step_timeout_ms'] = 0
        start(); self.hit(engine, 13)
        self.time = engine.deadline_us + 25_000; engine.tick()
        self.assertIsNotNone(engine.drain_payload)
        self.assertEqual(engine.failure['reason'], 'ROUND_TIMEOUT')
        self.assertEqual(engine.score(), 100)
        self.assertEqual(engine.solutions, 0)
        self.assertEqual(engine.leaderboard(), [])

    def test_pause_freezes_and_resumes_step_budget(self):
        engine, start = self.engine(); start()
        self.time += 3_000_000; engine._gesture('CLICK')
        before=engine.snapshot()['step_remaining_ms']
        self.time += 30_000_000; engine.tick()
        self.assertIsNone(engine.failure)
        self.assertEqual(engine.snapshot()['step_remaining_ms'], before)
        engine._gesture('CLICK')
        self.assertEqual(engine.snapshot()['step_remaining_ms'], before)

    def test_optional_node_does_not_extend_deadline(self):
        engine, start = self.engine(); start()
        before = engine.step_deadline_us
        self.hit(engine, 15)
        self.assertEqual(engine.step_deadline_us, before)

    def test_repeated_lambda_has_separate_nodes(self):
        engine, start = self.engine(mission='M07_EVENT_DRIVEN'); start()
        for button in (5,3): self.hit(engine,button)
        graph=engine.snapshot()['graph']
        states={n['node_id']:n['state'] for n in graph['nodes']}
        self.assertEqual(states['producer_lambda'],'live')
        self.assertEqual(states['worker_lambda'],'locked')
        for button in (8,3,4): self.hit(engine,button)
        self.assertEqual(engine.snapshot()['graph']['status'],'complete')

    def test_all_guided_missions_can_complete(self):
        for mission in load_missions():
            with self.subTest(mission=mission['id']):
                engine, start = self.engine(mission=mission['id']); start()
                for _ in range(len(mission['nodes'])):
                    pending=[n for n in frontier(mission,engine.done) if n['required']]
                    if not pending: break
                    self.hit(engine,engine.by_key[pending[0]['service']]['id'])
                self.assertEqual(engine.solutions, 1)
                self.assertIsNone(engine.failure)
                self.assertEqual(engine.snapshot()['graph']['status'],'complete')

    def test_rush_switch_clears_previous_panels_and_preserves_completed_graph(self):
        engine, start = self.engine('RUSH60_RANKED'); start()
        for button in (13,3,9,14): self.hit(engine,button)
        self.assertEqual(engine.mission_id,'M02_VISION')
        self.assertEqual(engine.snapshot()['graph']['connected_count'],0)
        self.assertNotIn('ACCEPTED',engine.panels.values())
        self.assertEqual(engine.last_completed_graph['status'],'complete')
        self.hit(engine,1)
        self.assertEqual(engine.solutions,1)
        self.assertEqual(engine.failure['reason'],'WRONG_SERVICE')

    def test_ranked_future_service_names_are_hidden(self):
        engine, start = self.engine('RUSH60_RANKED'); start()
        self.assertTrue(all(n['service'] is None for n in engine.snapshot()['graph']['nodes']))
        self.hit(engine,13)
        self.assertEqual(sum(n['service'] is not None for n in engine.snapshot()['graph']['nodes']),1)

    def test_free_selected_roles_do_not_fabricate_connected_paths(self):
        missions={m['id']:m for m in load_missions()}
        graph=project_graph(missions['M01_VOICE'],set(),Counter(LAMBDA=1,BEDROCK=1,POLLY=1))
        self.assertEqual(graph['connected_count'],0)
        self.assertFalse(any(e['state']=='live' for e in graph['edges']))
        graph=project_graph(missions['M07_EVENT_DRIVEN'],set(),Counter(LAMBDA=1,API_GATEWAY=1,SQS=1,DYNAMODB=1))
        nodes={n['node_id']:n for n in graph['nodes']}
        self.assertEqual(nodes['producer_lambda']['state'],'live')
        self.assertNotEqual(nodes['worker_lambda']['state'],'live')
        self.assertNotEqual(nodes['job_table']['state'],'live')

    def test_free_remove_and_undo_invalidate_candidate_graphs(self):
        engine, start=self.engine('FREE'); start()
        for button in (13,3,9,14): self.hit(engine,button)
        engine.analyze()
        self.assertTrue(engine.snapshot()['candidate_graphs'])
        engine.undo()
        self.assertEqual(engine.snapshot()['candidate_graphs'],{})
        for _ in range(5): engine.undo()
        self.assertFalse(any(engine.selected.values()))

    def test_rule_changes_are_isolated_in_pack_hash(self):
        original=load_game_config(); modified=deepcopy(original)
        modified['collapse']['step_timeout_ms'] += 1000
        self.assertNotEqual(pack_hash(original),pack_hash(modified))

    def test_workflows_have_unique_edges_known_endpoints_and_nonoverlapping_nodes(self):
        for mission in load_missions():
            graph=project_graph(mission,set())
            ids={n['node_id'] for n in graph['nodes']} | {'input','output'}
            self.assertEqual(len({e['id'] for e in graph['edges']}),len(graph['edges']))
            for edge in graph['edges']:
                self.assertIn(edge['source'],ids); self.assertIn(edge['target'],ids)
                self.assertNotEqual(edge['source'],edge['target'])
            for i,a in enumerate(graph['nodes']):
                self.assertLessEqual(a['x']+168,1280); self.assertLessEqual(a['y']+120+42,640)
                for b in graph['nodes'][i+1:]:
                    overlap=a['x']<b['x']+168 and a['x']+168>b['x'] and a['y']<b['y']+120 and a['y']+120>b['y']
                    self.assertFalse(overlap, (mission['id'],a['node_id'],b['node_id']))

if __name__=='__main__': unittest.main()
