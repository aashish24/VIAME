@echo off

REM Path to VIAME installation
SET VIAME_INSTALL=C:\Program Files\VIAME

REM Processing options
SET INPUT_DIRECTORY=videos
SET FRAME_RATE=5
SET START_TIME=00:00:00.00
SET DURATION=99:99:99.99
SET OUTPUT_DIR=frames

REM Setup paths and run command
CALL "%VIAME_INSTALL%\setup_viame.bat"

python.exe "%VIAME_INSTALL%\configs\extract_video_frames.py" ^
  -d "%INPUT_DIRECTORY%" -o %OUTPUT_DIR% ^
  -r %FRAME_RATE% -s %START_TIME% -t %DURATION%

pause
