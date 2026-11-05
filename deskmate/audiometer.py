"""How loud is the PC's sound right now? (Windows only: for dancing on the beat.)

Windows keeps a "peak meter" for every speaker: the same numbers that make the little green bar
move in the volume mixer. Reading it is cheap and private: it's one number (0..1), not the
sound itself. It uses the Core Audio COM interfaces through ctypes, so there's nothing to
install:

    IMMDeviceEnumerator -> default speakers (IMMDevice) -> IAudioMeterInformation.GetPeakValue()

If anything here fails (another OS, no speakers, unusual drivers), ``PeakMeter.level()`` returns
None and she simply dances at a steady tempo instead.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import time
import uuid

log = logging.getLogger(__name__)

CLSID_MMDeviceEnumerator = "BCDE0395-E52F-467C-8E3D-C4579291692E"
IID_IMMDeviceEnumerator = "A95664D2-9614-4F35-A746-DE8DB63617E6"
IID_IAudioMeterInformation = "C02216F6-8C67-4B5B-9D00-D008E73E0064"
CLSCTX_ALL = 0x17
E_RENDER, E_MULTIMEDIA = 0, 1  # speakers (not microphones), for music and videos
RETRY_AFTER = 5.0  # seconds before trying again after a failure (e.g. headphones unplugged)


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, text: str) -> "_GUID":
        return cls.from_buffer_copy(uuid.UUID(text).bytes_le)


def _method(pointer: ctypes.c_void_p, index: int, *argtypes):
    """A COM method: entry ``index`` of the object's table of functions (it returns an HRESULT)."""
    table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    prototype = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
    return prototype(table[index])


def _release(pointer: ctypes.c_void_p) -> None:
    if pointer:
        table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(table[2])(pointer)  # IUnknown::Release


class PeakMeter:
    def __init__(self):
        self._enumerator = ctypes.c_void_p()
        self._device = ctypes.c_void_p()
        self._meter = ctypes.c_void_p()
        self._failed_at = -1e9
        self.available = sys.platform == "win32"

    def _open(self) -> bool:
        ole32 = ctypes.WinDLL("ole32")
        ole32.CoInitializeEx(None, 0x2)  # (already set up by Qt on this thread: that's fine)
        if not self._enumerator:
            hr = ole32.CoCreateInstance(ctypes.byref(_GUID.of(CLSID_MMDeviceEnumerator)), None, CLSCTX_ALL,
                                        ctypes.byref(_GUID.of(IID_IMMDeviceEnumerator)),
                                        ctypes.byref(self._enumerator))
            if hr != 0:
                raise OSError(f"CoCreateInstance failed: {hr & 0xFFFFFFFF:#x}")
        get_default = _method(self._enumerator, 4, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))
        hr = get_default(self._enumerator, E_RENDER, E_MULTIMEDIA, ctypes.byref(self._device))
        if hr != 0:
            raise OSError(f"no speakers: {hr & 0xFFFFFFFF:#x}")
        activate = _method(self._device, 3, ctypes.POINTER(_GUID), ctypes.c_uint32, ctypes.c_void_p,
                           ctypes.POINTER(ctypes.c_void_p))
        hr = activate(self._device, ctypes.byref(_GUID.of(IID_IAudioMeterInformation)), CLSCTX_ALL, None,
                      ctypes.byref(self._meter))
        if hr != 0:
            raise OSError(f"no peak meter: {hr & 0xFFFFFFFF:#x}")
        return True

    def level(self) -> float | None:
        """The current loudness (0..1), or None if it can't be read."""
        if not self.available or time.monotonic() - self._failed_at < RETRY_AFTER:
            return None
        try:
            if not self._meter:
                self._open()
            value = ctypes.c_float()
            hr = _method(self._meter, 3, ctypes.POINTER(ctypes.c_float))(self._meter, ctypes.byref(value))
            if hr != 0:
                raise OSError(f"GetPeakValue failed: {hr & 0xFFFFFFFF:#x}")
            return max(0.0, min(1.0, value.value))
        except Exception as error:  # (e.g. the speakers changed: open them again in a few seconds)
            if self._failed_at < 0:
                log.info("No sound level (she'll dance at a steady tempo): %s", error)
            self._failed_at = time.monotonic()
            self.close(keep_enumerator=True)
            return None

    def close(self, keep_enumerator: bool = False) -> None:
        for name in ("_meter", "_device") + (() if keep_enumerator else ("_enumerator",)):
            pointer = getattr(self, name)
            try:
                _release(pointer)
            except Exception:
                pass
            setattr(self, name, ctypes.c_void_p())
