"""Comandos curtos de direção no Windows, sem alterar acelerador/travão.

SendInput usa scan codes. Um observador de teclado distingue ações físicas
das injetadas. Um temporizador independente liberta a tecla mesmo que o
diálogo Qt interrompa a atualização normal. Nunca há comandos no arranque.
"""
import ctypes as C
from ctypes import wintypes as W
import threading
import time
import xml.etree.ElementTree as ET
from radar_input import virtual_key, JoyCaps, JoyInfo


class KeyInput(C.Structure):
    _fields_ = [('vk', W.WORD), ('scan', W.WORD), ('flags', W.DWORD),
                ('time', W.DWORD), ('extra', C.c_size_t)]


class MouseInput(C.Structure):
    _fields_ = [('x', W.LONG), ('y', W.LONG), ('data', W.DWORD),
                ('flags', W.DWORD), ('time', W.DWORD), ('extra', C.c_size_t)]


class InputUnion(C.Union):
    _fields_ = [('keyboard', KeyInput), ('mouse', MouseInput)]


class Input(C.Structure):
    _fields_ = [('type', W.DWORD), ('value', InputUnion)]


class HookData(C.Structure):
    _fields_ = [('vk', W.DWORD), ('scan', W.DWORD), ('flags', W.DWORD),
                ('time', W.DWORD), ('extra', C.c_size_t)]


class SteeringInput:
    def __init__(self, radar):
        self.radar = radar
        self.keys = {}
        self.monitored = set()
        self.physical = set()
        self.manual_pressed = False
        self.axis = None
        self.message = 'Direção por configurar'
        self.held = None
        self.deadline = 0
        self.window = None
        self.hook = None
        self.lock = threading.RLock()
        self.done = threading.Event()
        self.thread = None
        self.hook_thread = None
        self.hook_ready = threading.Event()
        self.error = ''
        self.sent_pulses = 0
        if not radar.available:
            return
        self.user = C.WinDLL('user32', use_last_error=True)
        self.user.SendInput.argtypes = [W.UINT, C.POINTER(Input), C.c_int]
        self.user.SendInput.restype = W.UINT
        self.user.MapVirtualKeyW.argtypes = [W.UINT, W.UINT]
        self.user.MapVirtualKeyW.restype = W.UINT
        self.user.GetForegroundWindow.restype = W.HWND
        self.user.SetWindowsHookExW.argtypes = [C.c_int, C.c_void_p, W.HINSTANCE, W.DWORD]
        self.user.SetWindowsHookExW.restype = W.HHOOK
        self.user.CallNextHookEx.argtypes = [W.HHOOK, C.c_int, W.WPARAM, W.LPARAM]
        self.user.CallNextHookEx.restype = C.c_ssize_t
        self.user.UnhookWindowsHookEx.argtypes = [W.HHOOK]
        self.user.PeekMessageW.argtypes = [C.POINTER(W.MSG),W.HWND,W.UINT,W.UINT,W.UINT]
        self.user.TranslateMessage.argtypes = [C.POINTER(W.MSG)]
        self.user.DispatchMessageW.argtypes = [C.POINTER(W.MSG)]
        self.user.DispatchMessageW.restype = C.c_ssize_t
        callback = C.WINFUNCTYPE(C.c_ssize_t, C.c_int, W.WPARAM, W.LPARAM)
        self.callback = callback(self.on_key)
        # O hook tem o seu próprio ciclo de mensagens: a libertação de teclas
        # não fica dependente de o Qt estar disponível para executar callbacks.
        self.hook_thread = threading.Thread(target=self.watch_keyboard,daemon=True)
        self.hook_thread.start()
        self.hook_ready.wait(1)
        if not self.hook:
            self.message = 'Observação da direção indisponível no Windows'
            return
        self.thread = threading.Thread(target=self.watch_release, daemon=True)
        self.thread.start()

    def watch_keyboard(self):
        self.hook = self.user.SetWindowsHookExW(13,self.callback,None,0)
        self.hook_ready.set()
        message = W.MSG()
        try:
            while self.hook and not self.done.wait(.005):
                while self.user.PeekMessageW(C.byref(message),None,0,0,1):
                    self.user.TranslateMessage(C.byref(message))
                    self.user.DispatchMessageW(C.byref(message))
        finally:
            if self.hook:
                self.user.UnhookWindowsHookEx(self.hook)
                self.hook = None

    def on_key(self, code, message, pointer):
        """Só regista teclas físicas relevantes; nunca bloqueia a entrada do jogador."""
        if code >= 0:
            data = C.cast(pointer, C.POINTER(HookData)).contents
            if not data.flags & 0x10 and data.vk in self.monitored:
                if message in (0x100, 0x104):
                    self.physical.add(data.vk)
                    self.manual_pressed = True
                elif message in (0x101, 0x105):
                    self.physical.discard(data.vk)
        return self.user.CallNextHookEx(self.hook, code, message, pointer)

    def load(self):
        """Lê teclas simples e o eixo real; configurações não observáveis bloqueiam ativação."""
        self.release()
        self.keys = {}
        self.axis = None
        self.monitored = set()  # Apenas as teclas de direção representam intervenção manual.
        self.physical.clear()
        self.manual_pressed = False
        self.sent_pulses = 0
        try:
            if not self.hook or not self.radar.path:
                raise ValueError('Observação da direção ou perfil indisponível')
            root = ET.parse(self.radar.path).getroot()
            keys = {}
            for direction, tag in ((-1, 'SteerLeftButton'), (1, 'SteerRightButton')):
                action = root.find(tag)
                if action is None:
                    raise ValueError(f'Falta {tag} no perfil')
                for item in action:
                    if item.get('Device') in (None, '{NoDevice}'):
                        continue
                    vk = virtual_key(item.get('Device'), item.get('Key', ''))
                    if item.get('Device') != 'Keyboard' or vk is None or item.find('Modifier') is not None:
                        raise ValueError('Direção por botões: usar teclas simples, sem modificadores')
                    self.monitored.add(vk)
                    keys.setdefault(direction, vk)
            if len(keys)!=2 or keys[-1]==keys[1]:
                raise ValueError('Associar F6 a virar à esquerda e F7 a virar à direita nos controlos SRV')
            if 0x77 in keys.values():
                raise ValueError('F8 está reservado para ligar/desligar a assistência')
            for item in root.iter():
                if item.get('Device') == 'Keyboard' and item.get('Key') == 'Key_F8':
                    raise ValueError('F8 já está associado no jogo; libertar F8 antes de usar assistência')
            mouse = root.find('MouseBuggySteeringXMode')
            if mouse is not None and mouse.get('Value') not in (None, '', '0'):
                raise ValueError('Direção pelo rato ainda não suportada pela assistência')
            binding = root.find('SteeringAxis/Binding')
            if binding is not None and binding.get('Device') not in (None, '{NoDevice}'):
                index = self.radar.joystick_id(binding.get('Device'))
                # Identidade USB do TWCS; alguns drivers devolvem nome genérico.
                if index is None and binding.get('Device') == 'T16000MTHROTTLE':
                    matches = []
                    for i in range(min(16, self.radar.winmm.joyGetNumDevs())):
                        caps = JoyCaps()
                        if self.radar.winmm.joyGetDevCapsW(i,C.byref(caps),C.sizeof(caps))==0 and (caps.mid,caps.pid)==(0x044f,0xb687):
                            matches.append(i)
                    index = matches[0] if len(matches)==1 else None
                # WinMM chama R ao leme (RZ), não à rotação X. U/V podem
                # corresponder a sliders ou rotações conforme o dispositivo;
                # não inferir essas associações nesta primeira versão.
                axis = {'Joy_XAxis':'x','Joy_YAxis':'y','Joy_ZAxis':'z',
                        'Joy_RZAxis':'r'}.get(binding.get('Key'))
                if index is None or axis is None:
                    raise ValueError('Não foi possível observar o eixo de direção; assistência indisponível')
                caps = JoyCaps()
                if self.radar.winmm.joyGetDevCapsW(index,C.byref(caps),C.sizeof(caps)):
                    raise ValueError('Falha ao ler limites do eixo de direção')
                low, high = getattr(caps,axis+'min'), getattr(caps,axis+'max')
                if high<=low:
                    raise ValueError('Limites de direção inválidos')
                self.axis = (index, axis, low, high)
            self.keys = keys
            self.physical = {vk for vk in self.monitored if self.radar.user.GetAsyncKeyState(vk)&0x8000}
            self.message = 'F8: ligar/desligar · direção manual: desligar'
            self.error = ''
        except (OSError, ValueError, ET.ParseError) as exc:
            self.message = str(exc)

    def manual(self):
        """Inclui impulsos físicos curtos e posição do eixo; falha de dispositivo desliga."""
        pressed, self.manual_pressed = self.manual_pressed, False
        if pressed or self.physical:
            return True
        if self.axis:
            index, axis, low, high = self.axis
            info = JoyInfo()
            info.size, info.flags = C.sizeof(info), 0xff
            if self.radar.winmm.joyGetPosEx(index, C.byref(info)):
                return None
            value = (getattr(info,axis)-(low+high)/2)/((high-low)/2)
            return abs(value)>.05
        return False

    def send(self, vk, up=False):
        scan = self.user.MapVirtualKeyW(vk, 0)
        if not scan:
            raise OSError('Tecla de direção sem scan code')
        flags = 0x8 | (0x2 if up else 0) | (0x1 if vk in (33,34,35,36,37,38,39,40,45,46) else 0)
        item = Input(type=1, value=InputUnion(keyboard=KeyInput(0,scan,flags,0,0)))
        if self.user.SendInput(1,C.byref(item),C.sizeof(item))!=1:
            raise OSError('Windows não aceitou o comando de direção')

    def pulse(self, direction, duration):
        with self.lock:
            if self.held is not None or not self.keys or not self.radar.game_focused():
                return False
            vk = self.keys[direction]
            self.window = self.user.GetForegroundWindow()
            self.held = vk
            self.deadline = time.monotonic()+min(3.0,max(.01,duration))
            try:
                self.send(vk)
                self.sent_pulses += 1
                return True
            except OSError as exc:
                self.error = str(exc)
                self.release()
                return False

    def brake(self):
        """Comando de chegada pedido pelo utilizador: S durante três segundos."""
        with self.lock:
            self.release()
            if self.held is not None or not self.radar.game_focused():
                return False
            self.window = self.user.GetForegroundWindow()
            self.held = 0x53
            self.deadline = time.monotonic()+3.0
            try:
                self.send(self.held)
                return True
            except OSError as exc:
                self.error = str(exc)
                self.release()
                return False

    def hold_test(self, direction, remaining):
        """Mantém a direção do ensaio enquanto o Qt renova uma autorização curta.

        O ciclo dura 5 s, mas cada autorização dura no máximo 150 ms: se a
        interface parar de responder, a tecla é libertada pelo vigilante.
        """
        with self.lock:
            if not self.keys or not self.radar.game_focused() or remaining<=0:
                self.release()
                return False
            vk = self.keys[direction]
            if self.held != vk:
                self.release()
                if not self.pulse(direction,min(.1,remaining)):
                    return False
            self.deadline = time.monotonic()+min(.15,remaining)
            return True

    def release(self):
        with self.lock:
            if self.held is not None:
                try:
                    self.send(self.held, True)
                    self.held = None
                except OSError as exc:
                    self.error = str(exc)  # vigilante volta a tentar libertar

    def watch_release(self):
        """Liberta ao terminar o toque ou perder foco, independentemente do ciclo Qt."""
        while not self.done.wait(.005):
            with self.lock:
                if self.held is not None and (time.monotonic()>=self.deadline or self.user.GetForegroundWindow()!=self.window):
                    self.release()

    def close(self):
        self.release()
        self.done.set()
        if self.thread:
            self.thread.join(.2)
        if self.hook_thread:
            self.hook_thread.join(.2)
