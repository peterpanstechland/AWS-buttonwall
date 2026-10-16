import unittest
from wall_backend.engine import Engine
from wall_backend.store import Store
from wall_backend.serial_bridge import BwBridge
from reference.awg1 import START_GESTURE, BUTTON_HIT

class Port:
    def __init__(self): self.rx=b''; self.tx=[]; self.closed=False
    def read(self): data,self.rx=self.rx,b''; return data
    def write(self,data): self.tx.append(data)
    def close(self): self.closed=True

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.now=10000000; self.port=Port()
        self.e=Engine(Store(),clock_us=lambda:self.now)
        self.addCleanup(self.e.store.conn.close)
        self.b=BwBridge(self.e,'test',lambda path:self.port); self.e.bridge=self.b
        self.b.poll(); self.seq=0
    def hello(self,mask=0):
        self.port.rx=f'BW HELLO 2 123 {int(self.e.crc,16)} 100 {mask}\n'.encode(); self.b.poll()
        self.e.mcu.out=[]
    def state(self,mask,delta=50000):
        self.now+=delta; self.seq+=1
        self.port.rx=f'BW STATE 123 {self.seq} {self.now} {mask}\n'.encode(); self.b.poll()
    def test_handshake_and_physical_ui_boundary(self):
        self.assertIn(str(int(self.e.crc,16)).encode(),self.port.tx[0]); self.hello()
        s=self.e.snapshot();self.assertFalse(s['sim_input']);self.assertTrue(s['demo'])
        self.assertEqual(s['device_mode'],'bw_serial')
        with self.assertRaises(RuntimeError): self.e.sim_click(1)
        self.assertEqual(self.e.mcu.levels,[False]*17)
    def test_held_boot_requires_release(self):
        self.hello(2);self.assertFalse(self.b.ready)
        self.state(2);self.assertEqual(self.e.mcu.out,[])
        self.state(0);self.assertTrue(self.b.ready)
        self.state(2);self.assertEqual(self.e.mcu.out[0].msg_type,BUTTON_HIT)
    def test_short_press_is_not_debounced_twice(self):
        self.hello(); self.state(2); self.state(0,1000)
        self.assertEqual(sum(f.msg_type==BUTTON_HIT for f in self.e.mcu.out),1)
    def test_kiro_click_double_and_hold(self):
        self.hello()
        for kind in ('CLICK','DOUBLE'):
            self.e.mcu.reset_session(); self.e.mcu.out=[]
            self.state(1); self.state(0)
            if kind=='DOUBLE': self.state(1); self.state(0)
            self.now+=300001
            frames=self.e.mcu.poll(self.now)
            self.assertEqual([f.payload['gesture'] for f in frames if f.msg_type==START_GESTURE],[kind])
        # Isolated hold includes exactly one event and no click on release.
        self.e.mcu.out=[];self.state(1); self.now+=2000001
        frames=self.e.mcu.poll(self.now)
        self.assertEqual([f.payload['gesture'] for f in frames if f.msg_type==START_GESTURE],['HOLD'])
        self.state(0);self.now+=400000
        self.assertFalse(any(f.msg_type==START_GESTURE for f in self.e.mcu.poll(self.now)))
    def test_bad_crc_old_firmware_and_sequence_gap_fail_closed(self):
        self.port.rx=b'BW HELLO 2 123 0 100 0\n';self.b.poll();self.assertFalse(self.b.online)
        self.now+=1000001;self.b.poll();self.port.rx=b'BW PONG v0.8\n';self.b.poll()
        self.now+=1600000;self.b.poll();self.assertEqual(self.b.error,'LINK_TIMEOUT')
    def test_gap_and_timeout_cancel_pending_input(self):
        self.hello();self.e.state='ACTIVE';self.e.mode='FREE';self.e.session_id='test'
        self.port.rx=b'BW STATE 123 2 200 1\n';self.b.poll()
        self.assertFalse(self.b.online);self.assertEqual(self.e.state,'INTERRUPTED')
        self.assertEqual(self.e.mcu.levels,[False]*17)
    def test_light_transaction_ack_and_timeout(self):
        self.hello();self.b.lights();self.assertIsNotNone(self.b.pending)
        self.assertEqual(len(self.port.tx[-1].split()[-1]),128)
        self.port.rx=b'BW FRAME_OK 1 1\n';self.b.poll();self.assertTrue(self.b.applied)
        self.assertTrue(self.e.snapshot()['light_plan']['hardware_applied'])
        self.state(0,1600000);self.now+=1600000;self.b.poll()
        self.assertFalse(self.e.snapshot()['light_plan']['hardware_applied'])
    def test_fragmented_stream_and_out_of_order_rejection(self):
        raw=f'BW HELLO 2 123 {int(self.e.crc,16)} 100 0\n'.encode()
        for byte in raw:self.port.rx=bytes([byte]);self.b.poll()
        self.assertTrue(self.b.online)
        self.state(0);self.port.rx=f'BW STATE 123 1 {self.now} 0\n'.encode();self.b.poll()
        self.assertEqual(self.b.error,'INPUT_STREAM_GAP')


@unittest.skipUnless(__import__('sys').platform.startswith('linux'), 'Linux tty integration')
class LinuxSerialTests(unittest.TestCase):
    def test_real_tty_starts_free_game_from_physical_buttons(self):
        import os, pty, select
        master,slave=pty.openpty(); path=os.ttyname(slave)
        self.addCleanup(os.close,master); self.addCleanup(os.close,slave)
        now=[10000000]; e=Engine(Store(),clock_us=lambda:now[0]);self.addCleanup(e.store.conn.close)
        e.bridge=BwBridge(e,path);e.tick()
        self.addCleanup(lambda:e.bridge.port and e.bridge.port.close())
        self.assertTrue(select.select([master],[],[],1)[0])
        self.assertIn(b'BW GAME 2',os.read(master,8192))
        seq=0
        def send(line):
            os.write(master,(line+'\n').encode());e.tick()
        send(f'BW HELLO 2 123 {int(e.crc,16)} 100 0')
        def state(mask,delta=50000):
            nonlocal seq
            now[0]+=delta;seq+=1
            send(f'BW STATE 123 {seq} {now[0]} {mask}')
        state(1);state(0);state(0,310000)
        self.assertEqual(e.state,'MODE_LOBBY')
        # B1 selects FREE using the same mapping as the physical panel.
        state(1<<5);state(0)
        self.assertEqual(e.mode,'FREE')
        state(1);state(0);state(0,310000)
        self.assertEqual(e.state,'ACTIVE')
        state(1<<3);state(0)
        self.assertEqual(e.selected['LAMBDA'],1)
        self.assertFalse(e.snapshot()['sim_input'])
