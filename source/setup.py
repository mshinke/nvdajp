#setup.py
#A part of NonVisual Desktop Access (NVDA)
#Copyright (C) 2006-2007 NVDA Contributors <http://www.nvda-project.org/>
#This file is covered by the GNU General Public License.
#See the file COPYING for more details.

import os
import gettext
gettext.install("nvda", unicode=True)
from distutils.core import setup
import py2exe as py2exeModule
from glob import glob
import fnmatch
from versionInfo import *
from py2exe import build_exe
import wx
import imp

def getModuleExtention(thisModType):
	for ext,mode,modType in imp.get_suffixes():
		if modType==thisModType:
			return ext
	raise ValueError("unknown mod type %s"%thisModType)

# py2exe insists on excluding certain dlls that don't seem to exist on many systems, so hackishly force them to be included.
origIsSystemDLL = build_exe.isSystemDLL
def isSystemDLL(pathname):
	if os.path.basename(pathname).lower() in ("msvcp71.dll", "msvcp90.dll", "gdiplus.dll","mfc71.dll", "mfc90.dll"):
		return 0
	return origIsSystemDLL(pathname)
build_exe.isSystemDLL = isSystemDLL

class py2exe(build_exe.py2exe):
	"""Overridden py2exe command to:
		* Run generate.py first
		* Add files generated by generate.py to the data files list
		* Don't copy w9xpopen, as NVDA will never run on Win9x
	"""

	def run(self):
		# Run generate.py.
		import generate
		generate.main()
		# Add the files just generated.
		compiledModExtention=getModuleExtention(imp.PY_COMPILED)
		sourceModExtention=getModuleExtention(imp.PY_SOURCE)
		self.distribution.data_files.extend(
			[
				("comInterfaces", glob("comInterfaces/*%s"%compiledModExtention)),
				("appModules", glob("appModules/*%s"%compiledModExtention)),
			]
			+ getLocaleDataFiles()
			+ getRecursiveDataFiles("synthDrivers", "synthDrivers", excludes=("*%s"%sourceModExtention,))
			+ getRecursiveDataFiles("brailleDisplayDrivers", "brailleDisplayDrivers", excludes=("*%s"%sourceModExtention,))
		)
		build_exe.py2exe.run(self)

	def copy_w9xpopen(self, modules, dlls):
		pass

def getLocaleDataFiles():
	NVDALocaleFiles=[(os.path.dirname(f), (f,)) for f in glob("locale/*/LC_MESSAGES/*.mo")]
	wxDir=wx.__path__[0]
	wxLocaleFiles=[(os.path.dirname(f)[len(wxDir)+1:], (f,)) for f in glob(wxDir+"/locale/*/LC_MESSAGES/*.mo")]
	return NVDALocaleFiles+wxLocaleFiles

def getRecursiveDataFiles(dest,source,excludes=()):
	rulesList=[]
	rulesList.append((dest,
		[f for f in glob("%s/*"%source) if not any(fnmatch.fnmatch(f,exclude) for exclude in excludes) and os.path.isfile(f)]))
	[rulesList.extend(getRecursiveDataFiles(os.path.join(dest,dirName),os.path.join(source,dirName))) for dirName in os.listdir(source) if os.path.isdir(os.path.join(source,dirName)) and not dirName.startswith('.')]
	return rulesList

def getOptionalIncludes():
	includes = []
	try:
		# The explicit inclusion of brlapi is required because it is only imported by the brltty display driver, which is not a bundled module.
		import brlapi
		includes.append("brlapi")
	except:
		pass
	return includes

setup(
	name = name,
	version=version,
	description=description,
	url=url,
	classifiers=[
'Development Status :: 3 - Alpha',
'Environment :: Win32 (MS Windows)',
'Topic :: Adaptive Technologies'
'Intended Audience :: Developers',
'Intended Audience :: End Users/Desktop',
'License :: OSI Approved :: GNU General Public License (GPL)',
'Natural Language :: English',
'Programming Language :: Python',
'Operating System :: Microsoft :: Windows',
],
	cmdclass={"py2exe": py2exe},
	windows = [{
		"script":"nvda.pyw",
		"uac_info": ("asInvoker", False),
		"icon_resources":[(1,"images/nvda.ico")],
	}],
	options = {"py2exe": {
		"bundle_files": 3,
		"excludes": ["comInterfaces"],
		"packages": ["NVDAObjects","virtualBuffers_old","virtualBuffers"],
		# The explicit inclusion of ui can be removed once ui is imported by a bundled module.
		"includes": getOptionalIncludes(),
	}},
	zipfile = None,
	data_files=[
		(".",glob("*.dll")+glob("*.manifest")+["builtin.dic"]),
		("documentation", ['../copying.txt', '../contributors.txt']),
		("appModules", glob("appModules/*.kbd")),
		("lib", glob("lib/*")),
		("waves", glob("waves/*.wav")),
		("images", glob("images/*.ico")),
		("louis/tables",glob("louis/tables/*"))
	] + getRecursiveDataFiles('documentation', '../user_docs'),
)
