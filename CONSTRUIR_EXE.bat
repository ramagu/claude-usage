@echo off
chcp 65001 >nul
setlocal
rem Genera ClaudeUsage.exe para repartir al equipo. Solo hace falta
rem ejecutarlo en el equipo que tiene Python; los demas usan el .exe.
pushd "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo No se ha encontrado Python en el PATH.
  pause
  popd
  exit /b 1
)
python -m pip install --upgrade pyinstaller || goto :error
python -m PyInstaller --noconfirm --onefile --windowed ^
  --name ClaudeUsage ^
  --add-data "assets;assets" ^
  --icon "assets\bandeja.ico" ^
  "ClaudeUsage.pyw" || goto :error
echo.
echo Listo: dist\ClaudeUsage.exe
echo Cada persona lo ejecuta en su equipo y pega su propia SessionKey.
pause
popd
exit /b 0
:error
echo.
echo Fallo la generacion. Revise el mensaje de arriba.
pause
popd
exit /b 1
