@echo off
REM Double-click this file to open the ReEDS Surrogate dashboard in your browser.
REM Starts the Bokeh server if it isn't already running.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0code\launch_dashboard.ps1"
