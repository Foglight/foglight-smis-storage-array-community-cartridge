@echo off

REM Package the agent, this creates a new agent, but can also be used to
REM update a cartridge if the --create flags is changed to --update

set START=%cd%
set SDKDIR=D:\sdk\StorageSDK
set SDKLIBDIR=%SDKDIR%\lib
set HARNESS=%SDKDIR%\python-sdk\bin\cartridge-generator.bat
cd ..
set AGENTDIR=%cd%
set CONFIGDIR=%AGENTDIR%\config

rmdir /s/q state

cd %START%
%HARNESS% --create --name="SMISStorageAgent" ^
          --version "1.0.1" ^
          --libraries="%SDKLIBDIR%" ^
          --scripts="%AGENTDIR%"\src ^
          --properties="%CONFIGDIR%"\agent-properties.json ^
          --debug ^
          --collectors="%CONFIGDIR%"\agent-collectors.json %*
