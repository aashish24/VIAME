@echo off

# Setup VIAME Paths (no need to set if installed to registry or already set up)

SET VIAME_INSTALL=%~dp0\..\..\

SET KWIVER_PLUGIN_PATH=%KWIVER_PLUGIN_PATH%;%VIAME_INSTALL%\lib\modules
SET VIAME_PLUGIN_PATH=%VIAME_PLUGIN_PATH%;%VIAME_INSTALL%\lib\modules

# Run Pipeline

%VIAME_INSTALL%\bin\pipeline_runner.exe -p hello_world_detector.pipe

