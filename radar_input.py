"""Leitura passiva dos controlos configurados para o disparo primário SRV.

Não envia teclas ao jogo. Rato/teclado e botões de joystick WinMM até 32.
Associações não suportadas são apresentadas ao utilizador, nunca adivinhadas.
"""
import ctypes as C
from ctypes import wintypes as W
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def read_bindings(folder, selected=None):
    folder = Path(folder)
    if selected:
        path = Path(selected)
    else:
        preset_file = folder / 'StartPreset.4.start'
        lines = preset_file.read_text(encoding='utf-8-sig').splitlines()
        preset = (lines[2] if len(lines) >= 3 else lines[0]).strip()
        candidates = []
        for candidate in folder.glob('*.binds'):
            try:
                root = ET.parse(candidate).getroot()
                if root.get('PresetName') == preset:
                    candidates.append((int(root.get('MajorVersion', 0)),
                                       int(root.get('MinorVersion', 0)),
                                       candidate.stat().st_mtime_ns, candidate))
            except (ET.ParseError, ValueError):
                continue
        if not candidates:
            raise ValueError(f'Perfil SRV {preset!r} não encontrado. Escolha o .binds nas opções.')
        path = max(candidates)[-1]
    root = ET.parse(path).getroot()
    action = root.find('BuggyPrimaryFireButton')
    if action is None:
        raise ValueError('O perfil não contém disparo primário do SRV.')
    bindings = []
    for slot in ('Primary', 'Secondary'):
        item = action.find(slot)
        if item is not None and item.get('Device') not in (None, '{NoDevice}'):
            binding = [(item.get('Device'), item.get('Key', ''))]
            binding += [(m.get('Device'), m.get('Key', '')) for m in item.findall('Modifier')]
            bindings.append(binding)
    if not bindings:
        raise ValueError('Disparo primário SRV sem controlos associados.')
    return path, bindings


def virtual_key(device, key):
    if device == 'Mouse':
        return {'Mouse_1':1, 'Mouse_2':2, 'Mouse_3':4, 'Mouse_4':5, 'Mouse_5':6}.get(key)
    if device != 'Keyboard':
        return None
    name = key.removeprefix('Key_')
    if len(name) == 1 and name.isascii() and name.isalnum():
        return ord(name.upper())
    if re.fullmatch(r'F(?:[1-9]|1[0-9]|2[0-4])', name):
        return 111 + int(name[1:])
    return {'Space':32, 'Enter':13, 'Tab':9, 'Backspace':8, 'Escape':27,
            'LeftShift':160, 'RightShift':161, 'LeftControl':162, 'RightControl':163,
            'LeftAlt':164, 'RightAlt':165, 'UpArrow':38, 'DownArrow':40,
            'LeftArrow':37, 'RightArrow':39, 'Home':36, 'End':35,
            'PageUp':33, 'PageDown':34, 'Insert':45, 'Delete':46}.get(name)


class JoyCaps(C.Structure):
    _fields_ = [('mid', W.WORD), ('pid', W.WORD), ('name', W.WCHAR*32)] + [
        (n, W.UINT) for n in ('xmin','xmax','ymin','ymax','zmin','zmax','buttons',
        'pmin','pmax','rmin','rmax','umin','umax','vmin','vmax','caps','maxaxes','axes','maxbuttons')
    ] + [('regkey', W.WCHAR*32), ('oem', W.WCHAR*260)]


class JoyInfo(C.Structure):
    _fields_ = [(n, W.DWORD) for n in ('size','flags','x','y','z','r','u','v',
                                              'buttons','button','pov','reserved1','reserved2')]


class RadarInput:
    def __init__(self):
        self.bindings = []
        self.message = 'Controlos por carregar'
        self.path = None
        self.last_window = None
        self.last_focus_result = False
        self.joysticks = {}
        self.available = os.name == 'nt'
        if not self.available:
            self.message = 'Deteção de disparo disponível no Windows'
            return
        self.user = C.WinDLL('user32', use_last_error=True)
        self.kernel = C.WinDLL('kernel32', use_last_error=True)
        self.winmm = C.WinDLL('winmm')
        self.user.GetForegroundWindow.restype = W.HWND
        self.user.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
        self.user.GetAsyncKeyState.argtypes = [C.c_int]
        self.user.GetAsyncKeyState.restype = C.c_short
        self.kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        self.kernel.OpenProcess.restype = W.HANDLE
        self.kernel.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
        self.kernel.CloseHandle.argtypes = [W.HANDLE]
        self.winmm.joyGetDevCapsW.argtypes = [C.c_size_t, C.POINTER(JoyCaps), W.UINT]
        self.winmm.joyGetPosEx.argtypes = [W.UINT, C.POINTER(JoyInfo)]

    def load(self, selected=None):
        self.bindings = []
        if not self.available:
            return
        try:
            folder = Path(os.environ['LOCALAPPDATA'])/'Frontier Developments'/'Elite Dangerous'/'Options'/'Bindings'
            self.path, bindings = read_bindings(folder, selected)
            self.joysticks = {}
            for index in range(min(16, self.winmm.joyGetNumDevs())):
                caps = JoyCaps()
                if self.winmm.joyGetDevCapsW(index, C.byref(caps), C.sizeof(caps)) == 0:
                    name = re.sub('[^a-z0-9]', '', caps.name.lower())
                    self.joysticks.setdefault(name, []).append(index)
                    # Alguns drivers devolvem um nome genérico. Identificar
                    # o T.16000M pelos IDs evita escolher outro joystick.
                    if (caps.mid, caps.pid) == (0x044f, 0xb10a) and name != 't16000m':
                        self.joysticks.setdefault('t16000m', []).append(index)
            unsupported = []
            for binding in bindings:
                if all(self.supports(device, key) for device, key in binding):
                    self.bindings.append(binding)
                else:
                    unsupported.append(' + '.join(f'{d}/{k}' for d,k in binding))
            self.message = self.path.name + ': ' + ' ou '.join(
                ' + '.join(f'{d}/{k}' for d,k in binding) for binding in self.bindings)
            if unsupported:
                self.message += ' | Não disponível: ' + ', '.join(unsupported)
        except (OSError, ValueError, IndexError, KeyError, ET.ParseError) as exc:
            self.message = f'Controlos: {exc}'

    def joystick_id(self, device):
        name = re.sub('[^a-z0-9]', '', device.lower())
        matches = self.joysticks.get(name, [])
        return matches[0] if len(matches) == 1 else None

    def supports(self, device, key):
        if virtual_key(device, key) is not None:
            return True
        return bool(self.joystick_id(device) is not None and
                    re.fullmatch(r'Joy_(?:[1-9]|[12][0-9]|3[0-2])', key))

    def game_focused(self):
        if not self.available:
            return False
        pid = W.DWORD()
        window = self.user.GetForegroundWindow()
        if window == self.last_window:
            return self.last_focus_result
        self.last_window = window
        self.last_focus_result = False
        self.user.GetWindowThreadProcessId(window, C.byref(pid))
        handle = self.kernel.OpenProcess(0x1000, False, pid.value)
        if not handle:
            return False
        try:
            buffer = C.create_unicode_buffer(32768)
            size = W.DWORD(len(buffer))
            self.last_focus_result = bool(self.kernel.QueryFullProcessImageNameW(handle, 0, buffer, C.byref(size))
                        and Path(buffer.value).name.lower() == 'elitedangerous64.exe')
            return self.last_focus_result
        finally:
            self.kernel.CloseHandle(handle)

    def down(self):
        states = {}
        def pressed(device, key):
            vk = virtual_key(device, key)
            if vk is not None:
                return bool(self.user.GetAsyncKeyState(vk) & 0x8000)
            index = self.joystick_id(device)
            if index is None:
                return False
            if index not in states:
                info = JoyInfo()
                info.size, info.flags = C.sizeof(info), 0x80
                states[index] = info.buttons if self.winmm.joyGetPosEx(index, C.byref(info)) == 0 else 0
            return bool(states[index] & (1 << (int(key[4:])-1)))
        return any(all(pressed(d,k) for d,k in b) for b in self.bindings)
