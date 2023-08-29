SET ARGS=publisher=nvdajp release=1 version=%VERSION%
call scons nvdaHelper\client %ARGS%
cd jptools
cd nvdajpClient
copy ..\..\build\x86\client\nvdaController.h client
copy ..\..\build\x86\client\nvdaControllerClient32.dll client
copy ..\..\build\x86\client\nvdaControllerClient32.dll.pdb client
copy ..\..\build\x86\client\nvdaControllerClient32.exp client
copy ..\..\build\x86\client\nvdaControllerClient32.lib client
copy ..\..\build\x86_64\client\nvdaControllerClient64.dll client
copy ..\..\build\x86_64\client\nvdaControllerClient64.dll.pdb client
copy ..\..\build\x86_64\client\nvdaControllerClient64.exp client
copy ..\..\build\x86_64\client\nvdaControllerClient64.lib client
SET OUTFILE=..\..\output\nvda_%VERSION%_controllerClientJp.zip
del /Q %OUTFILE%
7z a %OUTFILE% client python license.txt readme.html readmejp.txt
cd ..
cd ..
