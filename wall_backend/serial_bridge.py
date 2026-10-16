"""BW2 USB bridge. Physical inputs with host timing; never ranked scoring.

No serial dependency on Linux/RDK. Bench BW SLOT firmware is deliberately rejected.
"""
from __future__ import annotations
import os
from wall_backend.mcu import VirtualMcu

class PosixPort:
    def __init__(self, path):
        import termios, tty
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            import fcntl
            fcntl.ioctl(self.fd, termios.TIOCEXCL)
            tty.setraw(self.fd)
            termios.tcflush(self.fd, termios.TCIOFLUSH)
        except Exception:
            os.close(self.fd)
            raise
    def read(self):
        try: return os.read(self.fd, 8192)
        except BlockingIOError: return b''
    def write(self, data):
        # Commands are small; never silently discard a partial nonblocking write.
        if os.write(self.fd, data) != len(data): raise OSError('partial serial write')
    def close(self):
        os.close(self.fd)

class PhysicalInputMcu(VirtualMcu):
    def accept_mask(self, mask, now):
        # Firmware already debounces. Preserve edge order, including short presses
        # when several state packets arrive in one read; do not debounce twice.
        self._gesture_timers(now)
        for i,key in enumerate(self.keys):
            down=bool(mask & (1<<i))
            if down == key.stable_down: continue
            key.candidate_since=now; key.confirmed_t=now
            key.context=self._context(); key.candidate_down=down
            self.levels[i]=down; key.stable_down=down
            if down:
                if i==0 and self.gesture['pending_click_at'] is not None and now<=self.gesture['pending_click_at']:
                    self.gesture['double_armed']=True
                self._on_press(i,key)
                self._gesture_timers(now)
            else: self._on_release(i,key)

class BwBridge:
    def __init__(self, engine, path, port_factory=PosixPort):
        self.engine=engine; self.path=path; self.factory=port_factory
        self.port=None; self.buffer=b''; self.online=False; self.ready=False
        self.error='CONNECTING'; self.retry_at=0; self.last_rx=0; self.last_keep=0
        self.seq=0; self.boot=None; self.last_device_us=-1
        self.frame_seq=0; self.pending=None; self.last_frame=None
        self.applied=False; self.lamps_ok=False
        engine.mcu=PhysicalInputMcu(engine.clock_us)

    def send(self, text):
        self.port.write((text+'\n').encode('ascii'))

    def disconnect(self, reason):
        had_link=self.online
        if self.port:
            try: self.port.close()
            except OSError: pass
        self.port=None; self.online=False; self.ready=False; self.applied=False
        self.error=reason; self.buffer=b''; self.pending=None; self.last_frame=None
        self.retry_at=self.engine.now()+1000000
        if had_link and self.engine.state in {'PREPARE','COUNTDOWN','ACTIVE','SETTLING'}:
            self.engine._interrupt('link')
        # Drop pending clicks on cable loss; never turn missing UP into a HOLD.
        self.engine.mcu=PhysicalInputMcu(self.engine.clock_us)
        self.engine._push('device.state')

    def line(self, text, now):
        p=text.split()
        if p[:2]==['BW','HELLO']:
            if len(p)!=7 or p[2]!='2' or int(p[4])!=int(self.engine.crc,16):
                raise ValueError('MAP_OR_VERSION_MISMATCH')
            if self.online: raise ValueError('UNEXPECTED_HELLO')
            mask=int(p[6]); device_us=int(p[5])
            if not 0<=mask<1<<17 or device_us<0: raise ValueError('BAD_HELLO')
            self.online=True; self.boot=int(p[3]); self.seq=0
            self.last_device_us=device_us; self.last_rx=now
            self.ready=mask==0; self.error=None if self.ready else 'RELEASE_ALL_KEYS'
            self.engine.mcu.boot_id='bw2-'+str(self.boot)
            self.engine.mcu.hello(); self.engine._push('device.state')
        elif p[:2]==['BW','STATE']:
            if not self.online or len(p)!=6: raise ValueError('STATE_WITHOUT_HELLO')
            boot,seq,device_us,mask=map(int,p[2:])
            if boot!=self.boot or seq!=self.seq+1 or device_us<self.last_device_us or not 0<=mask<1<<17:
                raise ValueError('INPUT_STREAM_GAP')
            self.seq=seq; self.last_device_us=device_us; self.last_rx=now
            if not self.ready:
                if mask==0:
                    self.ready=True; self.error=None
                    self.engine._push('device.state')
                return
            self.engine.mcu.accept_mask(mask,now)
        elif p[:2]==['BW','FRAME_OK']:
            if len(p)!=4: raise ValueError('BAD_FRAME_ACK')
            if self.pending and int(p[2])==self.pending[0]:
                self.lamps_ok=p[3]=='1'; self.applied=True; self.pending=None
        elif p[:2]==['BW','ERR']:
            raise ValueError('_'.join(p[2:]))
        elif p[:2]==['BW','PONG'] and self.online:
            raise ValueError('DEVICE_REBOOT')

    def poll(self):
        now=self.engine.now()
        try:
            if self.port is None:
                if now<self.retry_at:return
                self.port=self.factory(self.path); self.last_rx=now; self.last_keep=now
                self.send('BW GAME 2 '+str(int(self.engine.crc,16)))
            data=self.port.read()
            self.buffer+=data
            if len(self.buffer)>16384: raise ValueError('RX_OVERFLOW')
            while b'\n' in self.buffer:
                raw,self.buffer=self.buffer.split(b'\n',1)
                if len(raw)>255: raise ValueError('LINE_OVERFLOW')
                self.line(raw.decode('ascii').strip(),now)
            if now-self.last_rx>1500000: raise ValueError('LINK_TIMEOUT')
            if self.pending and now-self.pending[1]>1000000: raise ValueError('LIGHT_ACK_TIMEOUT')
            if self.online and now-self.last_keep>=500000:
                self.send('BW KEEP'); self.last_keep=now
        except (OSError,ValueError,UnicodeError) as exc:
            self.disconnect(str(exc))

    def lights(self):
        if not self.online or not self.ready:return
        effects={'off':0,'steady':1,'pulse':2,'breathe':3}
        plan=self.engine.light_plan(self.engine.navigation())
        data=bytearray(64)
        for cell in plan['cells']:
            i=(cell['button_id']-1)*4
            color=cell['color']; effect=effects.get(cell['effect'],0)
            data[i:i+4]=bytes([max(0,min(255,int(v))) for v in color]+[effect])
        encoded=data.hex()
        if encoded==self.last_frame or self.pending:return
        try:
            self.frame_seq+=1; self.pending=(self.frame_seq,self.engine.now())
            self.applied=False
            self.send(f'BW FRAME {self.frame_seq} {encoded}')
            self.last_frame=encoded
        except OSError as exc:self.disconnect(str(exc))

    def status(self):
        return {'online':self.online,'ready':self.ready,'error':self.error,
                'lights_acknowledged':self.applied,'button_lamps_ready':self.lamps_ok,
                'protocol':'BW2','timing':'host','ranked_eligible':False}
