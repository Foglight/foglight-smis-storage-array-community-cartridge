@echo off

REM You can customize this script to run out agent using the script harness

set START=%cd%
set SDKDIR=D:\sdk\StorageSDK
set SDKLIBDIR=%SDKDIR%\lib
set HARNESS=%SDKDIR%\python-sdk\bin\script-harness.bat
cd ..
set AGENTDIR=%cd%
set CONFIGDIR=%AGENTDIR%\config

set PROPERTIES=%CONFIGDIR%\agent-properties.json
if not "%1" == "" set PROPERTIES=%CONFIGDIR%\asp-%1.json

echo ""
echo "------------[ Starting SMIS Agent ]------------"
echo ""
echo "  Storage SDK dir:   %SDKDIR%"
echo "  Agent dir:   %AGENTDIR%"
echo "  Input properties:   %PROPERTIES%"
echo "  Persistent storage: %STATE_DIR%"
echo ""

cd %START%

%HARNESS% --properties=%PROPERTIES% ^
          --statedir=%AGENTDIR%\state ^
          --lib %SDKLIBDIR% ^
          %AGENTDIR%\src\smis-agent.py
