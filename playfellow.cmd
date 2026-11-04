@echo off
rem PlayFellow co-op launcher: runs the buddy and its tools with this folder's virtual environment, no activation needed.
rem   playfellow doctor | games | keys set | models | mcp | stk ...   or any play flags: playfellow --window "..." --overlay
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo PlayFellow is not installed here yet: run  powershell -ExecutionPolicy Bypass -File "%~dp0bootstrap.ps1"
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" -m playfellow_coop %*
