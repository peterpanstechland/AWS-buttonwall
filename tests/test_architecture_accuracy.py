"""Guard the technical distinctions found during the documentation audit."""
import unittest
from reference.catalog import load_missions, load_game_config
from wall_backend.graph import CONTENT, project_graph

class ArchitectureAccuracyTests(unittest.TestCase):
    def setUp(self):
        self.m = {m['id']:m for m in load_missions()}

    def pairs(self, mid):
        m=self.m[mid]; names={n['node_id']:n['service'] for n in m['nodes']}
        return {(names.get(e['source'],e['source']),names.get(e['target'],e['target'])) for e in CONTENT['missions'][mid]['edges']}

    def test_every_example_has_documentation_and_precise_edges(self):
        for mid,m in self.m.items():
            self.assertTrue(m['sources'],mid)
            self.assertTrue(all(s['url'].startswith('https://docs.aws.amazon.com/') for s in m['sources']))
            ids={n['node_id'] for n in m['nodes']}|{'input','output'}
            for e in CONTENT['missions'][mid]['edges']:
                self.assertTrue(set(e.get('requires',[]))<=ids)
                self.assertNotEqual(e['label']['en'],'Handoff')

    def test_no_fabricated_direct_integrations(self):
        self.assertNotIn(('BEDROCK','POLLY'),self.pairs('M01_VOICE'))
        self.assertIn(('LAMBDA','POLLY'),self.pairs('M01_VOICE'))
        self.assertNotIn(('REKOGNITION','DYNAMODB'),self.pairs('M02_VISION'))
        self.assertIn(('LAMBDA','DYNAMODB'),self.pairs('M02_VISION'))
        self.assertNotIn(('REKOGNITION','output'),self.pairs('M13_IMAGE_TAGS'))
        self.assertIn(('LAMBDA','S3'),self.pairs('M13_IMAGE_TAGS'))

    def test_cdn_origin_requests_and_api_auth_scope(self):
        for mid in ('M05_SERVERLESS_WEB','M06_CLASSIC_WEB','M09_PROTECTED_WEB','M12_STATIC_SITE'):
            self.assertIn(('CLOUDFRONT','S3'),self.pairs(mid))
        m=self.m['M09_PROTECTED_WEB']
        self.assertNotIn('Protected page',m['io']['output']['en'])
        self.assertNotIn(('COGNITO','S3'),self.pairs(m['id']))

    def test_endpoint_does_not_depend_on_its_caller(self):
        n={n['node_id']:n for n in self.m['M08_ML']['nodes']}
        self.assertEqual(n['model_host']['depends_on'],['dataset'])
        self.assertIn('model_host',n['infer_handler']['depends_on'])
        self.assertEqual(load_game_config()['pack']['pack_id'],'EVENT-20261016-B')

    def test_writes_wait_for_recognition_and_rush_hides_api_answers(self):
        m=self.m['M02_VISION']
        graph=project_graph(m,{'image_bucket','vision_trigger','vision_table'})
        write=next(e for e in graph['edges'] if e['target']=='vision_table')
        self.assertEqual(write['state'],'waiting')
        hidden=project_graph(m,set(),hide_answers=True)
        self.assertTrue(all(e['label']['en']=='Pending' for e in hidden['edges']))
