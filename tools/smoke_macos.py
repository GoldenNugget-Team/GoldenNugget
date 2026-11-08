import json
import os
import platform
import sys

if os.environ.get('TEST_ARCH'):
    assert platform.machine() == os.environ['TEST_ARCH'], platform.machine()
assert sys.version_info[:2] == (3,15)
import PySide6

assert PySide6.__version__ == '6.12.0', PySide6.__version__
from PySide6.QtCore import QStandardPaths

QStandardPaths.setTestModeEnabled(True)
import hashlib
import ssl
from compression import zstd

import cv2
import numpy
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from PySide6.QtWidgets import QApplication

cipher=Cipher(algorithms.AES(bytes(16)),modes.ECB()).encryptor()
assert cipher.update(bytes(16))+cipher.finalize()==bytes.fromhex('66e94bd4ef8a2c3b884cfa59ca342b2e')
assert zstd.decompress(zstd.compress(b'GoldenNugget'))==b'GoldenNugget'
assert len(hashlib.sha256(b'GoldenNugget').digest())==32
ssl.create_default_context()
assert cv2.cvtColor(numpy.zeros((2,2,3),dtype=numpy.uint8),cv2.COLOR_BGR2GRAY).shape==(2,2)
from types import SimpleNamespace

from src.devicemanagement.mobile_helper import find_engine
from src.gui.ios.daemons import IOSDaemonsContent
from src.tweaks.tweak_loader import load_daemons

# The bundled engine is what the Mobile helper execs, and it must be where the
# app's own resolver looks (sys._MEIPASS), not merely somewhere in the bundle.
engine=find_engine()
assert engine,'gn-sideload engine missing from the frozen bundle'
app=QApplication([])
load_daemons()
widget=IOSDaemonsContent(SimpleNamespace(settings=None,device_manager=None))
widget.resize(800,800)
widget.show()
app.processEvents()
assert widget.recover_notifications_button.text()
widget.close()
print(json.dumps({'frozen':getattr(sys,'frozen',False),'numpy':numpy.__version__,'opencv':cv2.__version__,'gui':'ok','crypto':'ok','engine':os.path.basename(engine)}))

print("MACOS_SMOKE_OK")
