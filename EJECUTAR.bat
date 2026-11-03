@echo off
chcp 65001 >nul
setlocal
rem Ejecuta la version en Python. Para el equipo se distribuye el .exe.
pushd "%~dp0"
where pythonw >nul 2>nul
if errorlevel 1 (
  echo No se ha encontrado Python en el PATH.
  echo Instale Python 3.10 o superior marcando "Add python.exe to PATH" y "tcl/tk and IDLE".
  pause
  popd
  exit /b 1
)
start "" pythonw "ClaudeUsage.pyw" %*
popd
