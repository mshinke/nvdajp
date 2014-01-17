# coding: utf-8
from __future__ import unicode_literals
import time
import ctypes
DLLPATH = r'..\client\nvdaControllerClient32.dll'
clientLib=ctypes.windll.LoadLibrary(DLLPATH)
res=clientLib.nvdaController_testIfRunning()
if res!=0:
	raise ctypes.WinError(res)
clientLib.nvdaController_speakText(
"""This is test case.
The case nvdaController_isSpeaking beep out when speaking with nvda!
""")
while clientLib.nvdaController_isSpeaking():
	time.sleep(0.5)
	ctypes.windll.kernel32.Beep(500, 100)
ctypes.windll.kernel32.Beep(1000, 100)
clientLib.nvdaController_cancelSpeech()
clientLib.nvdaController_speakText("Finished!")
