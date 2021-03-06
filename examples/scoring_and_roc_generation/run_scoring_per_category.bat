@echo off

REM Setup VIAME Paths (no need to set if installed to registry or already set up)

SET VIAME_INSTALL=.\..\..

CALL "%VIAME_INSTALL%\setup_viame.bat"

REM Run score tracks on data for singular metrics

python %VIAME_INSTALL%\configs\score_results.py ^
 -computed detections.csv -truth groundtruth.csv ^
 -threshold 0.05 -stats output_score_tracks.txt ^
 --per-category

REM Generate ROC

python %VIAME_INSTALL%\configs\score_results.py ^
 -computed detections.csv -truth groundtruth.csv ^
 -roc output_roc.png --per-category

pause
