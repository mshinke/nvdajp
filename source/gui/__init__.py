# -*- coding: UTF-8 -*-
# A part of NonVisual Desktop Access (NVDA)
# Copyright (C) 2006-2022 NV Access Limited, Peter Vágner, Aleksey Sadovoy, Mesar Hameed, Joseph Lee,
# Thomas Stivers, Babbage B.V., Accessolutions, Julien Cochuyt, Cyrille Bougot
# This file is covered by the GNU General Public License.
# See the file COPYING for more details.
# nvdajp modification by Takuya Nishimoto, Masataka.Shinke

import time
import os
import sys
import threading
import ctypes
import weakref
import wx
import wx.adv
import globalVars
import tones
import ui
from documentationUtils import getDocFilePath
from logHandler import log
import config
import versionInfo
import speech
import queueHandler
import core
from . import guiHelper
from .message import (
	isModalMessageBoxActive,
	# messageBox is accessed through `gui.messageBox` as opposed to `gui.message.messageBox` throughout NVDA,
	# be cautious when removing
	messageBox,
)
from .speechDict import (
	DefaultDictionaryDialog,
	VoiceDictionaryDialog,
	TemporaryDictionaryDialog,
)
from .settingsDialogs import (
	SettingsDialog,
)
from .settingsDialogs import *
from .startupDialogs import WelcomeDialog
from .inputGestures import InputGesturesDialog
from . import logViewer
import speechViewer
import winUser
import api
from utils.displayString import DisplayStringEnum
from enum import auto, unique
import languageHandler

try:
	import updateCheck
except RuntimeError:
	updateCheck = None

from . import jpBrailleViewer #nvdajp
import subprocess #nvdajp

def openDocFile(basename):
	d = getDocFilePath(basename + ".html")
	if config.conf["language"]["openDocFileByMSHTA"]:
		subprocess.Popen(["mshta.exe", d])
	else:
		os.startfile(d)

### Constants
NVDA_PATH = globalVars.appDir
ICON_PATH=os.path.join(NVDA_PATH, "images", "nvdajp3.ico")
DONATE_URL = "http://www.nvda.jp/donate.html"

### Globals
mainFrame = None


class MainFrame(wx.Frame):

	def __init__(self):
		style = wx.DEFAULT_FRAME_STYLE ^ wx.MAXIMIZE_BOX ^ wx.MINIMIZE_BOX | wx.FRAME_NO_TASKBAR
		super(MainFrame, self).__init__(None, wx.ID_ANY, versionInfo.name, size=(1,1), style=style)
		self.Bind(wx.EVT_CLOSE, self.onExitCommand)
		self.sysTrayIcon = SysTrayIcon(self)
		#: The focus before the last popup or C{None} if unknown.
		#: This is only valid before L{prePopup} is called,
		#: so it should be used as early as possible in any popup that needs it.
		#: @type: L{NVDAObject}
		self.prevFocus = None
		#: The focus ancestors before the last popup or C{None} if unknown.
		#: @type: list of L{NVDAObject}
		self.prevFocusAncestors = None
		# If NVDA has the uiAccess privilege, it can always set the foreground window.
		import systemUtils
		if not systemUtils.hasUiAccess():
			# This makes Windows return to the previous foreground window and also seems to allow NVDA to be brought to the foreground.
			self.Show()
			self.Hide()
			if winUser.isWindowVisible(self.Handle):
				# HACK: Work around a wx bug where Hide() doesn't actually hide the window,
				# but IsShown() returns False and Hide() again doesn't fix it.
				# This seems to happen if the call takes too long.
				self.Show()
				self.Hide()

	def prePopup(self):
		"""Prepare for a popup.
		This should be called before any dialog or menu which should pop up for the user.
		L{postPopup} should be called after the dialog or menu has been shown.
		@postcondition: A dialog or menu may be shown.
		"""
		nvdaPid = os.getpid()
		focus = api.getFocusObject()
		# Do not set prevFocus if the focus is on a control rendered by NVDA itself, such as the NVDA menu.
		# This allows to refer to the control that had focus before opening the menu while still using NVDA
		# on its own controls. The L{nvdaPid} check can be bypassed by setting the optional attribute
		# L{isPrevFocusOnNvdaPopup} to L{True} when a NVDA dialog offers customizable bound gestures,
		# eg. the NVDA Python Console.
		if focus.processID != nvdaPid or getattr(focus, "isPrevFocusOnNvdaPopup", False):
			self.prevFocus = focus
			self.prevFocusAncestors = api.getFocusAncestors()
		if winUser.getWindowThreadProcessID(winUser.getForegroundWindow())[0] != nvdaPid:
			# This process is not the foreground process, so bring it to the foreground.
			self.Raise()

	def postPopup(self):
		"""Clean up after a popup dialog or menu.
		This should be called after a dialog or menu was popped up for the user.
		"""
		self.prevFocus = None
		self.prevFocusAncestors = None
		if not winUser.isWindowVisible(winUser.getForegroundWindow()):
			# The current foreground window is invisible, so we want to return to the previous foreground window.
			# Showing and hiding our main window seems to achieve this.
			self.Show()
			self.Hide()

	def showGui(self):
		# The menu pops up at the location of the mouse, which means it pops up at an unpredictable location.
		# Therefore, move the mouse to the center of the screen so that the menu will always pop up there.
		location = api.getDesktopObject().location
		winUser.setCursorPos(*location.center)
		self.evaluateUpdatePendingUpdateMenuItemCommand()
		self.sysTrayIcon.onActivate(None)

	def onRevertToSavedConfigurationCommand(self,evt):
		queueHandler.queueFunction(queueHandler.eventQueue,core.resetConfiguration)
		# Translators: Reported when last saved configuration has been applied by using revert to saved configuration option in NVDA menu.
		queueHandler.queueFunction(queueHandler.eventQueue,ui.message,_("Configuration applied"))

	def onRevertToDefaultConfigurationCommand(self,evt):
		queueHandler.queueFunction(queueHandler.eventQueue,core.resetConfiguration,factoryDefaults=True)
		# Translators: Reported when configuration has been restored to defaults by using restore configuration to factory defaults item in NVDA menu.
		queueHandler.queueFunction(queueHandler.eventQueue,ui.message,_("Configuration restored to factory defaults"))

	def onSaveConfigurationCommand(self,evt):
		if globalVars.appArgs.secure:
			# Translators: Reported when current configuration cannot be saved while NVDA is running in secure mode such as in Windows login screen.
			queueHandler.queueFunction(queueHandler.eventQueue,ui.message,_("Cannot save configuration - NVDA in secure mode"))
			return
		try:
			config.conf.save()
			# Translators: Reported when current configuration has been saved.
			queueHandler.queueFunction(queueHandler.eventQueue,ui.message,_("Configuration saved"))
		except:
			# Translators: Message shown when current configuration cannot be saved such as when running NVDA from a CD.
			messageBox(_("Could not save configuration - probably read only file system"),_("Error"),wx.OK | wx.ICON_ERROR)

	def _popupSettingsDialog(self, dialog, *args, **kwargs):
		if isModalMessageBoxActive():
			return
		self.prePopup()
		try:
			dialog(self, *args, **kwargs).Show()
		except SettingsDialog.MultiInstanceErrorWithDialog as errorWithDialog:
			errorWithDialog.dialog.SetFocus()
		except MultiCategorySettingsDialog.CategoryUnavailableError:
			# Translators: Message shown when trying to open an unavailable category of a multi category settings dialog
			# (example: when trying to open touch interaction settings on an unsupported system).
			messageBox(_("The settings panel you tried to open is unavailable on this system."),_("Error"),style=wx.OK | wx.ICON_ERROR)

		self.postPopup()

	def onDefaultDictionaryCommand(self, evt):
		if not globalVars.appArgs.secure:
			self._popupSettingsDialog(DefaultDictionaryDialog)

	def onVoiceDictionaryCommand(self, evt):
		if not globalVars.appArgs.secure:
			self._popupSettingsDialog(VoiceDictionaryDialog)

	def onTemporaryDictionaryCommand(self, evt):
		if not globalVars.appArgs.secure:
			self._popupSettingsDialog(TemporaryDictionaryDialog)

	def onExecuteUpdateCommand(self, evt):
		if updateCheck and updateCheck.isPendingUpdate():
			destPath, version, apiVersion, backCompatToAPIVersion = updateCheck.getPendingUpdate()
			from addonHandler import getIncompatibleAddons
			if any(getIncompatibleAddons(apiVersion, backCompatToAPIVersion)):
				confirmUpdateDialog = updateCheck.UpdateAskInstallDialog(
					parent=gui.mainFrame,
					destPath=destPath,
					version=version,
					apiVersion=apiVersion,
					backCompatTo=backCompatToAPIVersion
				)
				gui.runScriptModalDialog(confirmUpdateDialog)
			else:
				updateCheck.executePendingUpdate()

	def evaluateUpdatePendingUpdateMenuItemCommand(self):
		try:
			self.sysTrayIcon.menu.Remove(self.sysTrayIcon.installPendingUpdateMenuItem)
		except:
			log.debug("Error while removing  pending update menu item", exc_info=True)
			pass
		if not globalVars.appArgs.secure and updateCheck and updateCheck.isPendingUpdate():
			self.sysTrayIcon.menu.Insert(self.sysTrayIcon.installPendingUpdateMenuItemPos,self.sysTrayIcon.installPendingUpdateMenuItem)

	def onExitCommand(self, evt):
		if isModalMessageBoxActive():
			return
		if config.conf["general"]["askToExit"]:
			self.prePopup()
			d = ExitDialog(self)
			d.Raise()
			d.Show()
			self.postPopup()
		else:
			if not core.triggerNVDAExit():
				log.error("NVDA already in process of exiting, this indicates a logic error.")

	def onNVDASettingsCommand(self,evt):
		self._popupSettingsDialog(NVDASettingsDialog)

	def onGeneralSettingsCommand(self,evt):
		self._popupSettingsDialog(NVDASettingsDialog, GeneralSettingsPanel)

	#nvdajp
	def onLanguageSettingsCommand(self,evt):
		self._popupSettingsDialog(LanguageSettingsDialog)

	def onSelectSynthesizerCommand(self,evt):
		self._popupSettingsDialog(SynthesizerSelectionDialog)

	def onSpeechSettingsCommand(self,evt):
		self._popupSettingsDialog(NVDASettingsDialog, SpeechSettingsPanel)

	def onSelectBrailleDisplayCommand(self,evt):
		self._popupSettingsDialog(BrailleDisplaySelectionDialog)

	def onBrailleSettingsCommand(self,evt):
		self._popupSettingsDialog(NVDASettingsDialog, BrailleSettingsPanel)

	def onKeyboardSettingsCommand(self,evt):
		self._popupSettingsDialog(NVDASettingsDialog, KeyboardSettingsPanel)

	def onMouseSettingsCommand(self,evt):
		self._popupSettingsDialog(NVDASettingsDialog, MouseSettingsPanel)

	def onTouchInteractionCommand(self,evt):
		self._popupSettingsDialog(NVDASettingsDialog, TouchInteractionPanel)

	def onReviewCursorCommand(self,evt):
		self._popupSettingsDialog(NVDASettingsDialog, ReviewCursorPanel)

	def onInputCompositionCommand(self,evt):
		self._popupSettingsDialog(NVDASettingsDialog, InputCompositionPanel)

	def onObjectPresentationCommand(self,evt):
		self._popupSettingsDialog(NVDASettingsDialog, ObjectPresentationPanel)

	def onBrowseModeCommand(self,evt):
		self._popupSettingsDialog(NVDASettingsDialog, BrowseModePanel)

	def onDocumentFormattingCommand(self,evt):
		self._popupSettingsDialog(NVDASettingsDialog, DocumentFormattingPanel)

	def onUwpOcrCommand(self, evt):
		self._popupSettingsDialog(NVDASettingsDialog, UwpOcrPanel)

	def onSpeechSymbolsCommand(self, evt):
		if globalVars.appArgs.secure:
			return
		self._popupSettingsDialog(SpeechSymbolsDialog)

	def onInputGesturesCommand(self, evt):
		if not globalVars.appArgs.secure:
			self._popupSettingsDialog(InputGesturesDialog)

	def onAboutCommand(self,evt):
		# Translators: The title of the dialog to show about info for NVDA.
		messageBox(versionInfo.aboutMessage, _("About NVDA"), wx.OK)

	def onCheckForUpdateCommand(self, evt):
		updateCheck.UpdateChecker().check()

	def onViewLogCommand(self, evt):
		logViewer.activate()

	def onSpeechViewerEnabled(self, isEnabled):
		# its possible for this to be called after the sysTrayIcon is destroyed if we are exiting NVDA
		if self.sysTrayIcon and self.sysTrayIcon.menu_tools_toggleSpeechViewer:
			self.sysTrayIcon.menu_tools_toggleSpeechViewer.Check(isEnabled)

	def onToggleSpeechViewerCommand(self, evt):
		if not speechViewer.isActive:
			speechViewer.activate()
		else:
			speechViewer.deactivate()

	def onBrailleViewerChangedState(self, created):
		# its possible for this to be called after the sysTrayIcon is destroyed if we are exiting NVDA
		if self.sysTrayIcon and self.sysTrayIcon.menu_tools_toggleBrailleViewer:
			self.sysTrayIcon.menu_tools_toggleBrailleViewer.Check(created)

	def onToggleBrailleViewerCommand(self, evt):
		import brailleViewer
		if brailleViewer.isBrailleViewerActive():
			brailleViewer.destroyBrailleViewer()
		else:
			brailleViewer.createBrailleViewerTool()

	def onPythonConsoleCommand(self, evt):
		import pythonConsole
		if not pythonConsole.consoleUI:
			pythonConsole.initialize()
		pythonConsole.activate()

	def onAddonsManagerCommand(self,evt):
		if isModalMessageBoxActive() or globalVars.appArgs.secure:
			return
		self.prePopup()
		from .addonGui import AddonsDialog
		d=AddonsDialog(gui.mainFrame)
		d.Show()
		self.postPopup()

	def onReloadPluginsCommand(self, evt):
		import appModuleHandler, globalPluginHandler
		from NVDAObjects import NVDAObject
		appModuleHandler.reloadAppModules()
		globalPluginHandler.reloadGlobalPlugins()
		NVDAObject.clearDynamicClassCache()

	#nvdajp begin
	def onToggleJpBrailleViewerCommand(self, evt):
		if not jpBrailleViewer.isActive:
			jpBrailleViewer.activate()
			self.sysTrayIcon.menu_tools_toggleJpBrailleViewer.Check(True)
		else:
			jpBrailleViewer.deactivate()
			self.sysTrayIcon.menu_tools_toggleJpBrailleViewer.Check(False)
	#nvdajp end
	
	def onCreatePortableCopyCommand(self,evt):
		if isModalMessageBoxActive():
			return
		self.prePopup()
		import gui.installerGui
		d=gui.installerGui.PortableCreaterDialog(gui.mainFrame)
		d.Show()
		self.postPopup()

	def onInstallCommand(self, evt):
		if isModalMessageBoxActive():
			return
		from gui import installerGui
		installerGui.showInstallGui()

	def onRunCOMRegistrationFixesCommand(self, evt):
		if isModalMessageBoxActive():
			return
		if messageBox(
			# Translators: A message to warn the user when starting the COM Registration Fixing tool 
			_("You are about to run the COM Registration Fixing tool. This tool will try to fix common system problems that stop NVDA from being able to access content in many programs including Firefox and Internet Explorer. This tool must make changes to the System registry and therefore requires administrative access. Are you sure you wish to proceed?"),
			# Translators: The title of the warning dialog displayed when launching the COM Registration Fixing tool 
			_("Warning"),wx.YES|wx.NO|wx.ICON_WARNING,self
		)==wx.NO:
			return
		progressDialog = IndeterminateProgressDialog(mainFrame,
			# Translators: The title of the dialog presented while NVDA is running the COM Registration fixing tool 
			_("COM Registration Fixing Tool"),
			# Translators: The message displayed while NVDA is running the COM Registration fixing tool 
			_("Please wait while NVDA tries to fix your system's COM registrations.")
		)
		try:
			import systemUtils
			systemUtils.execElevated(config.SLAVE_FILENAME, ["fixCOMRegistrations"])
		except:
			log.error("Could not execute fixCOMRegistrations command",exc_info=True) 
		progressDialog.done()
		del progressDialog
		messageBox(
			_(
				# Translators: The message displayed when the COM Registration Fixing tool completes.
				"The COM Registration Fixing tool has finished. "
				"It is highly recommended that you restart your computer now, to make sure the changes take full effect."
			),
			# Translators: The title of a dialog presented when the COM Registration Fixing tool is complete. 
			_("COM Registration Fixing Tool"),
			wx.OK
		)

	def onConfigProfilesCommand(self, evt):
		if isModalMessageBoxActive():
			return
		self.prePopup()
		from .configProfiles import ProfilesDialog
		ProfilesDialog(gui.mainFrame).Show()
		self.postPopup()

class SysTrayIcon(wx.adv.TaskBarIcon):

	def __init__(self, frame: MainFrame):
		super(SysTrayIcon, self).__init__()
		icon=wx.Icon(ICON_PATH,wx.BITMAP_TYPE_ICO)
		self.SetIcon(icon, versionInfo.name)

		self.menu=wx.Menu()
		menu_preferences=self.preferencesMenu=wx.Menu()
		item = menu_preferences.Append(wx.ID_ANY,
			# Translators: The label for the menu item to open NVDA Settings dialog.
			_("&Settings..."),
			# Translators: The description for the menu item to open NVDA Settings dialog.
			_("NVDA settings"))
		self.Bind(wx.EVT_MENU, frame.onNVDASettingsCommand, item)
		#nvdajp begin
		item = menu_preferences.Append(
			wx.ID_ANY,
			# Translators: The label for the menu item to open Language Settings dialog.
			_("Language settings..."),
			# Translators: The label for the menu item to open Language Settings dialog.
			_("Configure language dependent options")
		)
		self.Bind(wx.EVT_MENU, frame.onLanguageSettingsCommand, item)
		#nvdajp end
		if not globalVars.appArgs.secure:
			# TODO: This code should be moved out into a createSpeechDictsSubMenu function
			subMenu_speechDicts = wx.Menu()
			item = subMenu_speechDicts.Append(
				wx.ID_ANY,
				# Translators: The label for the menu item to open Default speech dictionary dialog.
				_("&Default dictionary..."),
				# Translators: The help text for the menu item to open Default speech dictionary dialog.
				_("A dialog where you can set default dictionary by adding dictionary entries to the list")
			)
			self.Bind(wx.EVT_MENU, frame.onDefaultDictionaryCommand, item)
			item = subMenu_speechDicts.Append(
				wx.ID_ANY,
				# Translators: The label for the menu item to open Voice specific speech dictionary dialog.
				_("&Voice dictionary..."),
				_(
					# Translators: The help text for the menu item
					# to open Voice specific speech dictionary dialog.
					"A dialog where you can set voice-specific dictionary by adding"
					" dictionary entries to the list"
				)
			)
			self.Bind(wx.EVT_MENU, frame.onVoiceDictionaryCommand, item)
			item = subMenu_speechDicts.Append(
				wx.ID_ANY,
				# Translators: The label for the menu item to open Temporary speech dictionary dialog.
				_("&Temporary dictionary..."),
				# Translators: The help text for the menu item to open Temporary speech dictionary dialog.
				_("A dialog where you can set temporary dictionary by adding dictionary entries to the edit box")
			)
			self.Bind(wx.EVT_MENU, frame.onTemporaryDictionaryCommand, item)
			# Translators: The label for a submenu under NvDA Preferences menu to select speech dictionaries.
			menu_preferences.AppendSubMenu(subMenu_speechDicts, _("Speech &dictionaries"))
		if not globalVars.appArgs.secure:
			# Translators: The label for the menu item to open Punctuation/symbol pronunciation dialog.
			item = menu_preferences.Append(wx.ID_ANY, _("&Punctuation/symbol pronunciation..."))
			self.Bind(wx.EVT_MENU, frame.onSpeechSymbolsCommand, item)
			# Translators: The label for the menu item to open the Input Gestures dialog.
			item = menu_preferences.Append(wx.ID_ANY, _("I&nput gestures..."))
			self.Bind(wx.EVT_MENU, frame.onInputGesturesCommand, item)
		# Translators: The label for Preferences submenu in NVDA menu.
		self.menu.AppendSubMenu(menu_preferences,_("&Preferences"))

		menu_tools = self.toolsMenu = wx.Menu()
		if not globalVars.appArgs.secure:
			# Translators: The label for the menu item to open NVDA Log Viewer.
			item = menu_tools.Append(wx.ID_ANY, _("View log"))
			self.Bind(wx.EVT_MENU, frame.onViewLogCommand, item)
		# Translators: The label for the menu item to toggle Speech Viewer.
		item = self.menu_tools_toggleSpeechViewer = menu_tools.AppendCheckItem(wx.ID_ANY, _("Speech viewer"))
		item.Check(speechViewer.isActive)
		self.Bind(wx.EVT_MENU, frame.onToggleSpeechViewerCommand, item)

		self.menu_tools_toggleBrailleViewer: wx.MenuItem = menu_tools.AppendCheckItem(
			wx.ID_ANY,
			# Translators: The label for the menu item to toggle Braille Viewer.
			_("Braille viewer")
		)
		item = self.menu_tools_toggleBrailleViewer
		self.Bind(wx.EVT_MENU, frame.onToggleBrailleViewerCommand, item)
		import brailleViewer
		self.menu_tools_toggleBrailleViewer.Check(brailleViewer.isBrailleViewerActive())
		brailleViewer.postBrailleViewerToolToggledAction.register(frame.onBrailleViewerChangedState)

		if not globalVars.appArgs.secure and not config.isAppX:
			# Translators: The label for the menu item to open NVDA Python Console.
			item = menu_tools.Append(wx.ID_ANY, _("Python console"))
			self.Bind(wx.EVT_MENU, frame.onPythonConsoleCommand, item)
			# Translators: The label of a menu item to open the Add-ons Manager.
			item = menu_tools.Append(wx.ID_ANY, _("Manage &add-ons..."))
			self.Bind(wx.EVT_MENU, frame.onAddonsManagerCommand, item)
		if not globalVars.appArgs.secure and not config.isAppX and getattr(sys,'frozen',None):
			# Translators: The label for the menu item to create a portable copy of NVDA from an installed or another portable version.
			item = menu_tools.Append(wx.ID_ANY, _("Create portable copy..."))
			self.Bind(wx.EVT_MENU, frame.onCreatePortableCopyCommand, item)
			if not config.isInstalledCopy():
				# Translators: The label for the menu item to install NVDA on the computer.
				item = menu_tools.Append(wx.ID_ANY, _("&Install NVDA..."))
				self.Bind(wx.EVT_MENU, frame.onInstallCommand, item)
			# Translators: The label for the menu item to run the COM registration fix tool 
			item = menu_tools.Append(wx.ID_ANY, _("Run COM Registration Fixing tool..."))
			self.Bind(wx.EVT_MENU, frame.onRunCOMRegistrationFixesCommand, item)
		if not config.isAppX:
			# Translators: The label for the menu item to reload plugins.
			item = menu_tools.Append(wx.ID_ANY, _("Reload plugins"))
			self.Bind(wx.EVT_MENU, frame.onReloadPluginsCommand, item)
		#nvdajp begin
		# Translators: The label for the menu item to open braille viewer.
		item = self.menu_tools_toggleJpBrailleViewer = menu_tools.AppendCheckItem(wx.ID_ANY, _("Japanese Braille viewer"))
		self.Bind(wx.EVT_MENU, frame.onToggleJpBrailleViewerCommand, item)
		#nvdajp end
		# Translators: The label for the Tools submenu in NVDA menu.
		self.menu.AppendSubMenu(menu_tools,_("Tools"))

		menu_help = self.helpMenu = wx.Menu()
		#nvdajp begin
		if not globalVars.appArgs.secure:
			item = menu_help.Append(wx.ID_ANY, _("&Readme (nvdajp)"))
			self.Bind(wx.EVT_MENU, lambda evt: openDocFile("readmejp"), item)
		#nvdajp end
		if not globalVars.appArgs.secure:
			# Translators: The label of a menu item to open NVDA user guide.
			item = menu_help.Append(wx.ID_ANY, _("&User Guide"))
			self.Bind(wx.EVT_MENU, lambda evt: openDocFile("userGuide"), item)
			# Translators: The label of a menu item to open the Commands Quick Reference document.
			item = menu_help.Append(wx.ID_ANY, _("Commands &Quick Reference"))
			self.Bind(wx.EVT_MENU, lambda evt: openDocFile("keyCommands"), item)
			# Translators: The label for the menu item to open What's New document.
			item = menu_help.Append(wx.ID_ANY, _("What's &new"))
			self.Bind(wx.EVT_MENU, lambda evt: openDocFile("changes"), item)
			item = menu_help.Append(wx.ID_ANY, _("NVDA &web site"))
			self.Bind(wx.EVT_MENU, lambda evt: os.startfile("http://www.nvda-project.org/"), item)
			# Translators: The label for the menu item to view NVDA License document.
			item = menu_help.Append(wx.ID_ANY, _("L&icense"))
			self.Bind(wx.EVT_MENU, lambda evt: os.startfile(getDocFilePath("copying.txt", False)), item)
			# Translators: The label for the menu item to view NVDA Contributors list document.
			item = menu_help.Append(wx.ID_ANY, _("C&ontributors"))
			self.Bind(wx.EVT_MENU, lambda evt: os.startfile(getDocFilePath("contributors.txt", False)), item)
			# Translators: The label for the menu item to open NVDA Welcome Dialog.
			item = menu_help.Append(wx.ID_ANY, _("We&lcome dialog..."))
			from .startupDialogs import WelcomeDialog
			self.Bind(wx.EVT_MENU, lambda evt: WelcomeDialog.run(), item)
			menu_help.AppendSeparator()
		if updateCheck:
			# Translators: The label of a menu item to manually check for an updated version of NVDA.
			item = menu_help.Append(wx.ID_ANY, _("&Check for update..."))
			self.Bind(wx.EVT_MENU, frame.onCheckForUpdateCommand, item)
		# Translators: The label for the menu item to open About dialog to get information about NVDA.
		item = menu_help.Append(wx.ID_ABOUT, _("About..."), _("About NVDA"))
		self.Bind(wx.EVT_MENU, frame.onAboutCommand, item)
		# Translators: The label for the Help submenu in NVDA menu.
		self.menu.AppendSubMenu(menu_help,_("&Help"))
		self.menu.AppendSeparator()
		# Translators: The label for the menu item to open the Configuration Profiles dialog.
		item = self.menu.Append(wx.ID_ANY, _("&Configuration profiles..."))
		self.Bind(wx.EVT_MENU, frame.onConfigProfilesCommand, item)
		# Translators: The label for the menu item to revert to saved configuration.
		item = self.menu.Append(wx.ID_ANY, _("&Revert to saved configuration"),_("Reset all settings to saved state"))
		self.Bind(wx.EVT_MENU, frame.onRevertToSavedConfigurationCommand, item)
		if not globalVars.appArgs.secure:
			# Translators: The label for the menu item to reset settings to default settings.
			# Here, default settings means settings that were there when the user first used NVDA.
			item = self.menu.Append(wx.ID_ANY, _("&Reset configuration to factory defaults"),_("Reset all settings to default state"))
			self.Bind(wx.EVT_MENU, frame.onRevertToDefaultConfigurationCommand, item)
			# Translators: The label for the menu item to save current settings.
			item = self.menu.Append(wx.ID_SAVE, _("&Save configuration"), _("Write the current configuration to nvda.ini"))
			self.Bind(wx.EVT_MENU, frame.onSaveConfigurationCommand, item)
			self.menu.AppendSeparator()
			# Translators: The label for the menu item to open donate page.
			item = self.menu.Append(wx.ID_ANY, _("Donate"))
			self.Bind(wx.EVT_MENU, lambda evt: os.startfile(DONATE_URL), item)
			self.installPendingUpdateMenuItemPos = self.menu.GetMenuItemCount()
			item = self.installPendingUpdateMenuItem = self.menu.Append(wx.ID_ANY,
				# Translators: The label for the menu item to run a pending update.
				_("Install pending &update"),
				# Translators: The description for the menu item to run a pending update.
				_("Execute a previously downloaded NVDA update"))
			self.Bind(wx.EVT_MENU, frame.onExecuteUpdateCommand, item)
		self.menu.AppendSeparator()
		item = self.menu.Append(wx.ID_EXIT, _("E&xit"),_("Exit NVDA"))
		self.Bind(wx.EVT_MENU, frame.onExitCommand, item)

		self.Bind(wx.adv.EVT_TASKBAR_LEFT_DOWN, self.onActivate)
		self.Bind(wx.adv.EVT_TASKBAR_RIGHT_DOWN, self.onActivate)

	def onActivate(self, evt):
		mainFrame.prePopup()
		import appModules.nvda
		if not appModules.nvda.nvdaMenuIaIdentity:
			# The NVDA app module doesn't know how to identify the NVDA menu yet.
			# Signal that the NVDA menu has just been opened.
			appModules.nvda.nvdaMenuIaIdentity = True
		self.PopupMenu(self.menu)
		if appModules.nvda.nvdaMenuIaIdentity is True:
			# The NVDA menu didn't actually appear for some reason.
			appModules.nvda.nvdaMenuIaIdentity = None
		mainFrame.postPopup()


def initialize():
	global mainFrame
	if mainFrame:
		raise RuntimeError("GUI already initialized")
	mainFrame = MainFrame()
	wxLang = core.getWxLangOrNone()
	if wxLang:
		# otherwise the system default will be used
		mainFrame.SetLayoutDirection(wxLang.LayoutDirection)
	wx.GetApp().SetTopWindow(mainFrame)
	import monkeyPatches
	monkeyPatches.applyWxMonkeyPatches(mainFrame, winUser, wx)


def terminate():
	global mainFrame
	mainFrame = None

def showGui():
 	wx.CallAfter(mainFrame.showGui)

def quit():
	wx.CallAfter(mainFrame.onExitCommand, None)


def runScriptModalDialog(dialog, callback=None):
	"""Run a modal dialog from a script.
	This will not block the caller,
	but will instead call C{callback} (if provided) with the result from the dialog.
	The dialog will be destroyed once the callback has returned.
	@param dialog: The dialog to show.
	@type dialog: C{wx.Dialog}
	@param callback: The optional callable to call with the result from the dialog.
	@type callback: callable
	"""
	def run():
		mainFrame.prePopup()
		res = dialog.ShowModal()
		mainFrame.postPopup()
		if callback:
			callback(res)
		dialog.Destroy()
	wx.CallAfter(run)


@unique
class _ExitAction(DisplayStringEnum):

	EXIT = auto()
	RESTART = auto()
	RESTART_WITH_ADDONS_DISABLED = auto()
	RESTART_WITH_DEBUG_LOGGING_ENABLED = auto()
	INSTALL_PENDING_UPDATE = auto()

	@property
	def _displayStringLabels(self):
		return {
			# Translators: An option in the combo box to choose exit action.
			self.EXIT: _("Exit"),
			# Translators: An option in the combo box to choose exit action.
			self.RESTART: _("Restart"),
			# Translators: An option in the combo box to choose exit action.
			self.RESTART_WITH_ADDONS_DISABLED: _("Restart with add-ons disabled"),
			# Translators: An option in the combo box to choose exit action.
			self.RESTART_WITH_DEBUG_LOGGING_ENABLED: _("Restart with debug logging enabled"),
			# Translators: An option in the combo box to choose exit action.
			self.INSTALL_PENDING_UPDATE: _("Install pending update"),
		}


class ExitDialog(wx.Dialog):
	_instance = None

	def __new__(cls, parent):
		# Make this a singleton.
		inst = cls._instance() if cls._instance else None
		if not inst:
			return super(cls, cls).__new__(cls, parent)
		return inst

	def __init__(self, parent):
		inst = ExitDialog._instance() if ExitDialog._instance else None
		if inst:
			return
		# Use a weakref so the instance can die.
		ExitDialog._instance = weakref.ref(self)
		# Translators: The title of the dialog to exit NVDA
		super(ExitDialog, self).__init__(parent, title=_("Exit NVDA"))
		dialog = self
		mainSizer = wx.BoxSizer(wx.VERTICAL)

		warningMessages = []
		contentSizerHelper = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

		if globalVars.appArgs.disableAddons:
			# Translators: A message in the exit Dialog shown when all add-ons are disabled.
			addonsDisabledText = _("All add-ons are now disabled. They will be re-enabled on the next restart unless you choose to disable them again.")
			warningMessages.append(addonsDisabledText)
		if languageHandler.isLanguageForced():
			langForcedMsg = _(
				# Translators: A message in the exit Dialog shown when NVDA language has been
				# overwritten from the command line.
				"NVDA's interface language is now forced from the command line."
				" On the next restart, the language  saved in NVDA's configuration will be used instead."
			)
			warningMessages.append(langForcedMsg)
		if warningMessages:
			contentSizerHelper.addItem(wx.StaticText(self, wx.ID_ANY, label="\n".join(warningMessages)))

		# Translators: The label for actions list in the Exit dialog.
		labelText=_("What would you like to &do?")
		allowedActions = list(_ExitAction)
		# Windows Store version of NVDA does not support add-ons yet.
		if config.isAppX:
			allowedActions.remove(_ExitAction.RESTART_WITH_ADDONS_DISABLED)
		# Changing debug level on secure screen is not allowed.
		# Logging on secure screens could allow keylogging of passwords and retrieval from the SYSTEM user.
		if globalVars.appArgs.secure:
			allowedActions.remove(_ExitAction.RESTART_WITH_DEBUG_LOGGING_ENABLED)
		# Installing updates should not happen in secure mode.
		if globalVars.appArgs.secure or not (updateCheck and updateCheck.isPendingUpdate()):
			allowedActions.remove(_ExitAction.INSTALL_PENDING_UPDATE)
		self.actions = [i.displayString for i in allowedActions]
		self.actionsList = contentSizerHelper.addLabeledControl(labelText, wx.Choice, choices=self.actions)
		self.actionsList.SetSelection(0)

		contentSizerHelper.addDialogDismissButtons(wx.OK | wx.CANCEL)

		self.Bind(wx.EVT_BUTTON, self.onOk, id=wx.ID_OK)
		self.Bind(wx.EVT_BUTTON, self.onCancel, id=wx.ID_CANCEL)

		mainSizer.Add(contentSizerHelper.sizer, border=guiHelper.BORDER_FOR_DIALOGS, flag=wx.ALL)
		mainSizer.Fit(self)
		self.Sizer = mainSizer
		self.actionsList.SetFocus()
		self.CentreOnScreen()

	def onOk(self, evt):
		action = [a for a in _ExitAction if a.displayString == self.actionsList.GetStringSelection()][0]
		if action == _ExitAction.EXIT:
			WelcomeDialog.closeInstances()
			if core.triggerNVDAExit():
				# there's no need to destroy ExitDialog in this instance as triggerNVDAExit will do this
				return
			else:
				log.error("NVDA already in process of exiting, this indicates a logic error.")
				return
		elif action == _ExitAction.RESTART:
			queueHandler.queueFunction(queueHandler.eventQueue,core.restart)
		elif action == _ExitAction.RESTART_WITH_ADDONS_DISABLED:
			queueHandler.queueFunction(queueHandler.eventQueue,core.restart,disableAddons=True)
		elif action == _ExitAction.RESTART_WITH_DEBUG_LOGGING_ENABLED:
			queueHandler.queueFunction(queueHandler.eventQueue,core.restart,debugLogging=True)
		elif action == _ExitAction.INSTALL_PENDING_UPDATE:
			if updateCheck:
				destPath, version, apiVersion, backCompatTo = updateCheck.getPendingUpdate()
				from addonHandler import getIncompatibleAddons
				if any(getIncompatibleAddons(currentAPIVersion=apiVersion, backCompatToAPIVersion=backCompatTo)):
					confirmUpdateDialog = updateCheck.UpdateAskInstallDialog(
						parent=gui.mainFrame,
						destPath=destPath,
						version=version,
						apiVersion=apiVersion,
						backCompatTo=backCompatTo
					)
					confirmUpdateDialog.ShowModal()
				else:
					updateCheck.executePendingUpdate()
		wx.CallAfter(self.Destroy)

	def onCancel(self, evt):
		self.Destroy()

class ExecAndPump(threading.Thread):
	"""Executes the given function with given args and kwargs in a background thread while blocking and pumping in the current thread."""

	def __init__(self,func,*args,**kwargs):
		self.func=func
		self.args=args
		self.kwargs=kwargs
		fname = repr(func)
		super().__init__(
			name=f"{self.__class__.__module__}.{self.__class__.__qualname__}({fname})"
		)
		self.threadExc=None
		self.start()
		time.sleep(0.1)
		threadHandle=ctypes.c_int()
		threadHandle.value=ctypes.windll.kernel32.OpenThread(0x100000,False,self.ident)
		msg=ctypes.wintypes.MSG()
		while ctypes.windll.user32.MsgWaitForMultipleObjects(1,ctypes.byref(threadHandle),False,-1,255)==1:
			while ctypes.windll.user32.PeekMessageW(ctypes.byref(msg),None,0,0,1):
				ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
				ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
		if self.threadExc:
			raise self.threadExc

	def run(self):
		try:
			self.func(*self.args,**self.kwargs)
		except Exception as e:
			self.threadExc=e
			log.debugWarning("task had errors",exc_info=True)

class IndeterminateProgressDialog(wx.ProgressDialog):

	def __init__(self, parent, title, message):
		super(IndeterminateProgressDialog, self).__init__(title, message, parent=parent)
		self._speechCounter = -1
		self.timer = wx.PyTimer(self.Pulse)
		self.timer.Start(1000)
		self.Raise()
		self.CentreOnScreen()

	def Pulse(self):
		super(IndeterminateProgressDialog, self).Pulse()
		# We want progress to be spoken on the first pulse and every 10 pulses thereafter.
		# Therefore, cycle from 0 to 9 inclusive.
		self._speechCounter = (self._speechCounter + 1) % 10
		pbConf = config.conf["presentation"]["progressBarUpdates"]
		if pbConf["progressBarOutputMode"] == "off":
			return
		if not pbConf["reportBackgroundProgressBars"] and not self.IsActive():
			return
		if pbConf["progressBarOutputMode"] in ("beep", "both"):
			tones.beep(440, 40)
		if pbConf["progressBarOutputMode"] in ("speak", "both") and self._speechCounter == 0:
			# Translators: Announced periodically to indicate progress for an indeterminate progress bar.
			speech.speakMessage(_("Please wait"))

	def IsActive(self):
		#4714: In wxPython 3, ProgressDialog.IsActive always seems to return False.
		return winUser.isDescendantWindow(winUser.getForegroundWindow(), self.Handle)

	def done(self):
		self.timer.Stop()
		pbConf = config.conf["presentation"]["progressBarUpdates"]
		if pbConf["progressBarOutputMode"] in ("beep", "both") and (pbConf["reportBackgroundProgressBars"] or self.IsActive()):
			tones.beep(1760, 40)
		self.Hide()
		self.Destroy()

def shouldConfigProfileTriggersBeSuspended():
	"""Determine whether configuration profile triggers should be suspended in relation to NVDA's GUI.
	For NVDA configuration dialogs, the configuration should remain the same as it was before the GUI was popped up
	so the user can change settings in the correct profile.
	Top-level windows that require this behavior should have a C{shouldSuspendConfigProfileTriggers} attribute set to C{True}.
	Because these dialogs are often opened via the NVDA menu, this applies to the NVDA menu as well.
	"""
	if winUser.getGUIThreadInfo(ctypes.windll.kernel32.GetCurrentThreadId()).flags & 0x00000010:
		# The NVDA menu is active.
		return True
	for window in wx.GetTopLevelWindows():
		if window.IsShown() and getattr(window, "shouldSuspendConfigProfileTriggers", False):
			return True
	return False

class NonReEntrantTimer(wx.Timer):
	"""
	Before WXPython 4, wx.Timer was nonre-entrant, 
	meaning that if code within its callback pumped messages (E.g. called wx.Yield) and this timer was ready to fire again, 
	the timer would not fire until the first callback had completed.
	However, in WXPython 4, wx.Timer is now re-entrant.
	Code in NVDA is not written to handle re-entrant timers, so this class provides a Timer with the old behaviour.
	This should be used in place of wx.Timer and wx.PyTimer where the callback will directly or indirectly call wx.Yield or some how process the Windows window message queue. 
	For example, NVDA's core pump or other timers that run in NVDA's main thread.
	Timers on braille display drivers for key detection don't need to use this as they only queue gestures rather than actually executing them.  
	"""

	def __init__(self, run=None):
		if run is not None:
			self.run = run
		self._inNotify = False
		super(NonReEntrantTimer,self).__init__()

	def run(self):
		"""Subclasses can override or specify in constructor.
		"""
		raise NotImplementedError

	def Notify(self):
		if self._inNotify:
			return
		self._inNotify = True
		try:
			self.run()
		finally:
			self._inNotify = False

def _isDebug():
	return config.conf["debugLog"]["gui"]
