#brailleDisplayDrivers/baum.py
#A part of NonVisual Desktop Access (NVDA)
#This file is covered by the GNU General Public License.
#See the file COPYING for more details.
#Copyright (C) 2010-2011 James Teh <jamie@jantrid.net>

import time
import wx
import serial
import hwPortUtils
import braille
import inputCore
from logHandler import log

TIMEOUT = 0.2
BAUD_RATE = 19200
READ_INTERVAL = 50

ESCAPE = "\x1b"

BAUM_DISPLAY_DATA = "\x01"
BAUM_CELL_COUNT = "\x01"
BAUM_PROTOCOL_ONOFF = "\x15"
BAUM_COMMUNICATION_CHANNEL = "\x16"
BAUM_POWERDOWN = "\x17"
BAUM_ROUTING_KEYS = "\x22"
BAUM_DISPLAY_KEYS = "\x24"
BAUM_BRAILLE_KEYS = "\x33"
BAUM_JOYSTICK_KEYS = "\x34"
BAUM_DEVICE_ID = "\x84"
BAUM_SERIAL_NUMBER = "\x8A"

BAUM_RSP_LENGTHS = {
	BAUM_CELL_COUNT: 1,
	BAUM_POWERDOWN: 1,
	BAUM_COMMUNICATION_CHANNEL: 1,
	BAUM_DISPLAY_KEYS: 1,
	BAUM_BRAILLE_KEYS: 2,
	BAUM_JOYSTICK_KEYS: 1,
	BAUM_DEVICE_ID: 16,
	BAUM_SERIAL_NUMBER: 8,
}

KEY_NAMES = {
	BAUM_ROUTING_KEYS: None,
	BAUM_DISPLAY_KEYS: ("d1", "d2", "d3", "d4", "d5", "d6"),
	BAUM_BRAILLE_KEYS: ("b9", "b10", "b11", None, "c1", "c2", "c3", "c4", # byte 1
		"b1", "b2", "b3", "b4", "b5", "b6", "b7", "b8"), # byte 2
	BAUM_JOYSTICK_KEYS: ("up", "left", "down", "right", "select"),
}

USB_IDS = frozenset((
	"VID_0403&PID_FE70", # Vario 40
	"VID_0403&PID_FE71", # PocketVario
	"VID_0403&PID_FE72", # SuperVario/Brailliant 40
	"VID_0403&PID_FE73", # SuperVario/Brailliant 32
	"VID_0403&PID_FE74", # SuperVario/Brailliant 64
	"VID_0403&PID_FE75", # SuperVario/Brailliant 80
	"VID_0403&PID_FE76", # VarioPro 80
	"VID_0403&PID_FE77", # VarioPro 64
	"VID_0904&PID_2000", # VarioPro 40
	"VID_0904&PID_2001", # EcoVario 24
	"VID_0904&PID_2002", # EcoVario 40
	"VID_0904&PID_2007", # VarioConnect/BrailleConnect 40
	"VID_0904&PID_2008", # VarioConnect/BrailleConnect 32
	"VID_0904&PID_2009", # VarioConnect/BrailleConnect 24
	"VID_0904&PID_2010", # VarioConnect/BrailleConnect 64
	"VID_0904&PID_2011", # VarioConnect/BrailleConnect 80
	"VID_0904&PID_2014", # EcoVario 32
	"VID_0904&PID_2015", # EcoVario 64
	"VID_0904&PID_2016", # EcoVario 80
	"VID_0904&PID_3000", # RefreshaBraille 18
))

BLUETOOTH_NAMES = (
	"Baum SuperVario",
	"Baum PocketVario",
	"Baum SVario",
	"HWG Brailliant",
	"Refreshabraille",
	"VarioConnect",
	"BrailleConnect",
)

class BrailleDisplayDriver(braille.BrailleDisplayDriver):
	name = "baum"
	description = _("Baum/HumanWare/APH braille displays")

	@classmethod
	def check(cls):
		return True

	def __init__(self):
		super(BrailleDisplayDriver, self).__init__()
		self.numCells = 0
		self._deviceID = None

		# Scan all available com ports.
		# Try bluetooth ports last.
		for portInfo in sorted(hwPortUtils.listComPorts(onlyAvailable=True), key=lambda item: "bluetoothName" in item):
			port = portInfo["port"]
			hwID = portInfo["hardwareID"]
			if hwID.startswith(r"FTDIBUS\COMPORT"):
				# USB.
				portType = "USB"
				try:
					usbID = hwID.split("&", 1)[1]
				except IndexError:
					continue
				if usbID not in USB_IDS:
					continue
			elif "bluetoothName" in portInfo:
				# Bluetooth.
				portType = "bluetooth"
				btName = portInfo["bluetoothName"]
				if not any(btName.startswith(prefix) for prefix in BLUETOOTH_NAMES):
					continue
			else:
				continue

			# At this point, a port bound to this display has been found.
			# Try talking to the display.
			try:
				self._ser = serial.Serial(port, baudrate=BAUD_RATE, timeout=TIMEOUT, writeTimeout=TIMEOUT)
			except serial.SerialException:
				continue
			# This will cause the number of cells to be returned.
			self._sendRequest(BAUM_DISPLAY_DATA)
			# Send again in case the display misses the first one.
			self._sendRequest(BAUM_DISPLAY_DATA)
			# We just sent less bytes than we should,
			# so we need to send another request in order for the display to know the previous request is finished.
			self._sendRequest(BAUM_DEVICE_ID)
			self._handleResponses(wait=True)
			if self.numCells:
				# A display responded.
				if not self._deviceID:
					# Bah. The response to our device ID query hasn't arrived yet, so wait for it.
					self._handleResponses(wait=True)
				log.info("Found {device} connected via {type} ({port})".format(
					device=self._deviceID, type=portType, port=port))
				break

		else:
			raise RuntimeError("No Baum display found")

		self._readTimer = wx.PyTimer(self._handleResponses)
		self._readTimer.Start(READ_INTERVAL)
		self._keysDown = {}
		self._ignoreKeyReleases = False

	def terminate(self):
		try:
			super(BrailleDisplayDriver, self).terminate()
			self._readTimer.Stop()
			self._readTimer = None
			self._sendRequest(BAUM_PROTOCOL_ONOFF, False)
		finally:
			# We absolutely must close the Serial object, as it does not have a destructor.
			# If we don't, we won't be able to re-open it later.
			self._ser.close()

	def _sendRequest(self, command, arg=""):
		if isinstance(arg, (int, bool)):
			arg = chr(arg)
		self._ser.write("\x1b{command}{arg}".format(command=command,
			arg=arg.replace(ESCAPE, ESCAPE * 2)))

	def _handleResponses(self, wait=False):
		while wait or self._ser.inWaiting():
			command, arg = self._readPacket()
			if command:
				self._handleResponse(command, arg)
			wait = False

	def _readPacket(self):
		# Find the escape.
		chars = []
		escapeFound = False
		while True:
			char = self._ser.read(1)
			if char == ESCAPE:
				escapeFound = True
				break
			else:
				chars.append(char)
			if not self._ser.inWaiting():
				break
		if chars:
			log.debugWarning("Ignoring data before escape: %r" % "".join(chars))
		if not escapeFound:
			return None, None

		command = self._ser.read(1)
		length = BAUM_RSP_LENGTHS.get(command, 0)
		if command == BAUM_ROUTING_KEYS:
			length = self.numCells / 8
		arg = self._ser.read(length)
		return command, arg

	def _handleResponse(self, command, arg):
		updateKeys = False
		executeKeys = False

		if command == BAUM_CELL_COUNT:
			self.numCells = ord(arg)
		elif command == BAUM_DEVICE_ID:
			self._deviceID = arg

		elif command in KEY_NAMES:
			updateKeys = True
			arg = sum(ord(byte) << offset * 8 for offset, byte in enumerate(arg))
			if arg < self._keysDown.get(command, 0):
				# Release.
				if not self._ignoreKeyReleases:
					# The first key released executes the key combination.
					executeKeys = True
			else:
				# Press.
				# This begins a new key combination.
				self._ignoreKeyReleases = False

		elif command == BAUM_POWERDOWN:
			log.debug("Power down")
		elif command in (BAUM_COMMUNICATION_CHANNEL, BAUM_SERIAL_NUMBER):
			pass

		else:
			log.debugWarning("Unknown command {command!r}, arg {arg!r}".format(command=command, arg=arg))

		if executeKeys:
			try:
				inputCore.manager.executeGesture(InputGesture(self._keysDown))
			except inputCore.NoInputGestureAction:
				pass
			# Any further releases are just the rest of the keys in the combination being released,
			# so they should be ignored.
			self._ignoreKeyReleases = True
		if updateKeys:
			# We must update key state after execution instead of before because
			# execution needs to include the key that was just released.
			self._keysDown[command] = arg

	def display(self, cells):
		# cells will already be padded up to numCells.
		self._sendRequest(BAUM_DISPLAY_DATA, "".join(chr(cell) for cell in cells))

	gestureMap = inputCore.GlobalGestureMap({
		"globalCommands.GlobalCommands": {
			"braille_scrollBack": ("br(baum):d2",),
			"braille_scrollForward": ("br(baum):d5",),
			"braille_previousLine": ("br(baum):d1",),
			"braille_nextLine": ("br(baum):d3",),
			"braille_routeTo": ("br(baum):routing",),
			"kb:upArrow": ("br(baum):up",),
			"kb:downArrow": ("br(baum):down",),
			"kb:leftArrow": ("br(baum):left",),
			"kb:rightArrow": ("br(baum):right",),
			"kb:enter": ("br(baum):select",),
		},
	})

class InputGesture(braille.BrailleDisplayGesture):

	source = BrailleDisplayDriver.name

	def __init__(self, keysDown):
		super(InputGesture, self).__init__()
		self.keysDown = dict(keysDown)

		self.keyNames = names = set()
		for group, groupKeysDown in keysDown.iteritems():
			if group == BAUM_ROUTING_KEYS:
				for index in xrange(braille.handler.display.numCells):
					if groupKeysDown & (1 << index):
						self.routingIndex = index
						names.add("routing")
						break
			else:
				for index, name in enumerate(KEY_NAMES[group]):
					if groupKeysDown & (1 << index):
						names.add(name)

		self.id = "+".join(names)
