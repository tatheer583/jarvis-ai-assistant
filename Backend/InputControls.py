"""Native Windows input and window operations, shared by the desktop shells."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import re
import time
from Backend.ActionResult import ActionResult
from Backend.Tasks import checkpoint

KEYS = {'ctrl': 0x11, 'alt': 0x12, 'shift': 0x10, 'win': 0x5B,
        'enter': 0x0D, 'tab': 0x09, 'escape': 0x1B, 'space': 0x20,
        'backspace': 0x08, 'delete': 0x2E, 'insert': 0x2D,
        'left': 0x25, 'up': 0x26, 'right': 0x27, 'down': 0x28,
        'home': 0x24, 'end': 0x23, 'pageup': 0x21, 'pagedown': 0x22,
        'plus': 0xBB, 'minus': 0xBD, 'comma': 0xBC, 'period': 0xBE}
KEYS.update({f'f{i}': 0x6F + i for i in range(1, 25)})
KEYS.update({c: ord(c.upper()) for c in 'abcdefghijklmnopqrstuvwxyz0123456789'})

def key_codes(text):
    text = text.lower().strip()
    for before, after in [('page down', 'pagedown'), ('page up', 'pageup'), ('control', 'ctrl'),
                          ('windows', 'win'), ('return', 'enter'), ('esc', 'escape'), ('arrow ', '')]:
        text = re.sub(r'\b' + re.escape(before) + (r'\b' if not before.endswith(' ') else ''), after, text)
    parts = [x for x in re.split(r'\s*\+\s*|\s+', text) if x and x != 'and']
    if not parts or len(parts) > 5 or len(set(parts)) != len(parts) or any(p not in KEYS for p in parts):
        raise ValueError('Use a keyboard shortcut such as press control shift s, press enter, or press F5.')
    if len(parts) > 1 and any(p not in {'ctrl', 'alt', 'shift', 'win'} for p in parts[:-1]):
        raise ValueError('Put modifiers first, such as control shift s.')
    return [KEYS[p] for p in parts]

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD), ('dwFlags', wintypes.DWORD),
                ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_size_t)]
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('mouseData', wintypes.DWORD),
                ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_size_t)]
class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [('uMsg', wintypes.DWORD), ('wParamL', wintypes.WORD), ('wParamH', wintypes.WORD)]
class INPUTUNION(ctypes.Union):
    _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT), ('hi', HARDWAREINPUT)]
class INPUT(ctypes.Structure):
    _fields_ = [('type', wintypes.DWORD), ('value', INPUTUNION)]

def send_inputs(events):
    checkpoint()
    array = (INPUT * len(events))(*events)
    send = ctypes.windll.user32.SendInput
    send.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    send.restype = wintypes.UINT
    if send(len(array), array, ctypes.sizeof(INPUT)) != len(array):
        raise OSError('Windows blocked input. Select the app and try again. Administrator windows may require matching permissions.')

def send_chord(codes):
    events = [INPUT(type=1, value=INPUTUNION(ki=KEYBDINPUT(wVk=code))) for code in codes]
    events += [INPUT(type=1, value=INPUTUNION(ki=KEYBDINPUT(wVk=code, dwFlags=2))) for code in reversed(codes)]
    send_inputs(events)

def send_unicode(text):
    encoded = text.replace('\r\n', '\n').encode('utf-16-le')
    events = []
    for offset in range(0, len(encoded), 2):
        checkpoint()
        code = int.from_bytes(encoded[offset:offset + 2], 'little')
        if code in (10, 9):
            vk = 0x0D if code == 10 else 0x09
            events.extend([INPUT(type=1, value=INPUTUNION(ki=KEYBDINPUT(wVk=vk))),
                           INPUT(type=1, value=INPUTUNION(ki=KEYBDINPUT(wVk=vk, dwFlags=2)))])
        else:
            events.extend([INPUT(type=1, value=INPUTUNION(ki=KEYBDINPUT(wScan=code, dwFlags=4))),
                           INPUT(type=1, value=INPUTUNION(ki=KEYBDINPUT(wScan=code, dwFlags=6)))])
        if len(events) >= 64:
            send_inputs(events)
            events = []
    if events:
        send_inputs(events)

class InputControls:
    grid_region = None
    grid_monitor = None
    excluded_pids = None

    def _focus(self, hwnd=None):
        import win32con
        import win32gui
        hwnd = hwnd or self.last_external_window
        if not hwnd or not win32gui.IsWindow(hwnd):
            raise RuntimeError('Select the destination app first, then say your command.')
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        if win32gui.GetForegroundWindow() != hwnd:
            # An Alt tap permits a normal foreground request without attaching input threads.
            send_chord([0x12])
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.1)
        if win32gui.GetForegroundWindow() != hwnd:
            raise RuntimeError('Windows could not focus the destination. Select it and try again.')
        self.last_external_window = hwnd
        return hwnd

    def keyboard(self, text, count=1):
        try:
            codes = key_codes(text)
            if not 1 <= count <= 20:
                raise ValueError('Repeat a key between 1 and 20 times.')
            if codes[0] != 0x5B:
                self._focus()
            for _ in range(count):
                checkpoint()
                send_chord(codes)
                if count > 1:
                    time.sleep(0.04)
            return ActionResult.ok('keys', f'Pressed {text}' + (f' {count} times.' if count > 1 else '.'))
        except Exception as exc:
            return ActionResult.fail('keys', str(exc))

    def type_text(self, text):
        try:
            self._focus()
            send_unicode(text)
            return ActionResult.ok('type', 'Typed the text into your selected app.')
        except Exception as exc:
            return ActionResult.fail('type', str(exc))

    def window_action(self, hwnd, operation):
        try:
            import win32con
            import win32gui
            import win32api
            if not win32gui.IsWindow(hwnd):
                raise ValueError('That window has already closed.')
            title = win32gui.GetWindowText(hwnd)
            if operation == 'focus':
                self._focus(hwnd)
            elif operation in {'minimize', 'maximize', 'restore'}:
                win32gui.ShowWindow(hwnd, {'minimize': win32con.SW_MINIMIZE, 'maximize': win32con.SW_MAXIMIZE, 'restore': win32con.SW_RESTORE}[operation])
            elif operation in {'snap left', 'snap right'}:
                self._focus(hwnd)
                work = win32api.GetMonitorInfo(win32api.MonitorFromWindow(hwnd))['Work']
                left, top, right, bottom = work
                width = (right - left) // 2
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetWindowPos(hwnd, 0, left if operation == 'snap left' else left + width, top,
                                     width, bottom - top, win32con.SWP_NOZORDER)
            else:
                raise ValueError('Unknown window action.')
            return ActionResult.ok('window', f'{operation.title()}: {title}.')
        except Exception as exc:
            return ActionResult.fail('window', str(exc))

    def mouse(self, operation, **options):
        try:
            import win32api
            import win32con
            amount = options.get('amount', 100)
            if operation in {'move', 'scroll'} and not 1 <= amount <= (2000 if operation == 'move' else 30):
                raise ValueError('Choose up to 2,000 pixels or 30 scroll steps.')
            if operation in {'move', 'position', 'center'}:
                x, y = win32api.GetCursorPos()
                if operation == 'move':
                    dx, dy = {'up': (0, -amount), 'down': (0, amount), 'left': (-amount, 0), 'right': (amount, 0)}[options['direction']]
                    x, y = x + dx, y + dy
                elif operation == 'position':
                    x, y = options['x'], options['y']
                else:
                    bounds = win32api.GetMonitorInfo(win32api.MonitorFromPoint((x, y)))['Monitor']
                    x, y = (bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2
                left, top = win32api.GetSystemMetrics(76), win32api.GetSystemMetrics(77)
                right, bottom = left + win32api.GetSystemMetrics(78), top + win32api.GetSystemMetrics(79)
                if not left <= x < right or not top <= y < bottom:
                    raise ValueError('That position is outside your displays.')
                checkpoint()
                win32api.SetCursorPos((x, y))
                if win32api.GetCursorPos() != (x, y):
                    raise RuntimeError("The pointer did not reach the requested position.")
            elif operation == 'scroll':
                direction = options['direction']
                value = amount * 120 * (1 if direction in {'up', 'right'} else -1)
                flag = 0x01000 if direction in {'left', 'right'} else 0x00800
                send_inputs([INPUT(type=0, value=INPUTUNION(mi=MOUSEINPUT(mouseData=value & 0xFFFFFFFF, dwFlags=flag)))])
            else:
                flags = {'click': (2, 4), 'left click': (2, 4), 'double click': (2, 4), 'right click': (8, 16), 'middle click': (32, 64)}
                down, up = flags[operation]
                for _ in range(2 if operation == 'double click' else 1):
                    send_inputs([INPUT(type=0, value=INPUTUNION(mi=MOUSEINPUT(dwFlags=down))),
                                 INPUT(type=0, value=INPUTUNION(mi=MOUSEINPUT(dwFlags=up)))])
                    time.sleep(0.06)
            return ActionResult.ok('mouse', f'Done: {operation}.')
        except Exception as exc:
            return ActionResult.fail('mouse', str(exc))

    def grid(self, operation, cell=None):
        import win32api
        if operation == 'hide':
            self.grid_region = None
            return ActionResult.ok('grid', 'Mouse grid hidden.', grid=None)
        if operation == 'show':
            self.grid_monitor = win32api.GetMonitorInfo(win32api.MonitorFromPoint(win32api.GetCursorPos()))
            self.grid_region = list(self.grid_monitor['Monitor'])
        else:
            if self.grid_region is None:
                return ActionResult.fail('grid', 'Say show grid first, then zoom five or click five.')
            if cell is None or not 1 <= cell <= 9:
                return ActionResult.fail('grid', 'Choose a grid number from one to nine.')
            left, top, right, bottom = self.grid_region
            row, column = divmod(cell - 1, 3)
            width, height = (right - left) / 3, (bottom - top) / 3
            bounds = [round(left + column * width), round(top + row * height), round(left + (column + 1) * width), round(top + (row + 1) * height)]
            if operation == 'zoom':
                if min(width, height) < 8:
                    return ActionResult.fail('grid', 'The grid is already precise. Say click and a number.')
                self.grid_region = bounds
            else:
                position = self.mouse('position', x=(bounds[0] + bounds[2]) // 2, y=(bounds[1] + bounds[3]) // 2)
                if not position.success:
                    return position
                result = self.mouse(operation)
                self.grid_region = None
                return ActionResult(result.success, 'grid', result.message, {'grid': None}, result.error)
        return ActionResult.ok('grid', 'Say zoom and a number to narrow the grid, or click and a number.',
                               grid={'bounds': self.grid_region, 'monitor': self.grid_monitor['Monitor'], 'device': self.grid_monitor['Device']})

    def click_control(self, text):
        try:
            from pywinauto import Desktop as WindowsDesktop
            hwnd = self._focus()
            elements = WindowsDesktop(backend='uia').window(handle=hwnd).descendants()
            matches = []
            for item in elements:
                checkpoint()
                try:
                    if item.element_info.control_type in {'Button', 'Hyperlink', 'MenuItem', 'TabItem', 'CheckBox', 'RadioButton', 'ListItem', 'TreeItem', 'ComboBox'} and item.is_visible() and item.is_enabled():
                        name = item.window_text().strip()
                        if name and text.casefold() in name.casefold():
                            matches.append((item, name))
                except Exception:
                    continue
            exact = [item for item in matches if item[1].casefold() == text.casefold()]
            matches = exact or matches
            if len(matches) != 1:
                return ActionResult.fail('click_control', 'Several controls match. Use a more specific name or say show grid.' if matches else 'That control is not available by name. Say show grid to click its position.')
            item, name = matches[0]
            checkpoint()
            item.click_input()
            return ActionResult.ok('click_control', f'Clicked {name}.')
        except Exception as exc:
            return ActionResult.fail('click_control', f'Could not click that control: {exc}. You can use the mouse grid.')

    def set_volume(self, value):
        try:
            if not 0 <= value <= 100:
                raise ValueError('Volume must be between 0 and 100 percent.')
            import pythoncom
            from pycaw.pycaw import AudioUtilities
            pythoncom.CoInitialize()
            try:
                endpoint = AudioUtilities.GetSpeakers().EndpointVolume
                endpoint.SetMasterVolumeLevelScalar(value / 100.0, None)
            finally:
                pythoncom.CoUninitialize()
            return ActionResult.ok('volume', f'Volume set to {value} percent.')
        except Exception as exc:
            return ActionResult.fail('volume', str(exc))
