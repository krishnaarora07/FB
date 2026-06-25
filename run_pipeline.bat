@echo off
:: Football Pipeline Scheduled Launcher
:: Registered in Windows Task Scheduler for:
::   - 9:00 AM IST  (morning run — captures European overnight news)
::   - 8:00 PM IST  (evening run — global peak viewing hours)

cd /d C:\Users\krish\Documents\fb

:: Create logs directory
set LOG_DIR=C:\Users\krish\Documents\fb\logs
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

:: Timestamped log file
set "DATESTAMP=%date:~-4%-%date:~3,2%-%date:~0,2%"
set "TIMESTAMP=%time:~0,2%%time:~3,2%"
set "TIMESTAMP=%TIMESTAMP: =0%"
set "LOGFILE=%LOG_DIR%\pipeline_%DATESTAMP%_%TIMESTAMP%.log"

echo [%date% %time%] ============================== >> "%LOGFILE%"
echo [%date% %time%] Football Pipeline Starting...  >> "%LOGFILE%"
echo [%date% %time%] ============================== >> "%LOGFILE%"

:: Use the system Python (where the package is installed via pip install -e .)
set PYTHON=C:\Python314\python.exe

:: Verify Python exists
if not exist "%PYTHON%" (
    echo [%date% %time%] ERROR: Python not found at %PYTHON% >> "%LOGFILE%"
    exit /b 1
)

:: Run the pipeline using python -m (works whether installed as script or editable install)
"%PYTHON%" -m football_pipeline.cli run --render --upload --cleanup >> "%LOGFILE%" 2>&1

set EXIT_CODE=%errorlevel%
echo. >> "%LOGFILE%"
echo [%date% %time%] Pipeline finished. Exit code: %EXIT_CODE% >> "%LOGFILE%"

:: Keep only last 30 log files to avoid disk bloat
powershell -NoProfile -Command "Get-ChildItem '%LOG_DIR%' -Filter 'pipeline_*.log' | Sort-Object CreationTime -Descending | Select-Object -Skip 30 | Remove-Item -Force" 2>nul

exit /b %EXIT_CODE%
