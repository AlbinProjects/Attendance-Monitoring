@echo off
schtasks /Delete /TN "Attendance Desktop Activity Agent" /F
echo Attendance Desktop Activity Agent scheduled task removed.
