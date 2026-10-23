@echo off
REM Start backend and frontend in two separate windows
start "campus-backend" cmd /k "%~dp0start-backend.bat"
start "campus-frontend" cmd /k "%~dp0start-frontend.bat"
start "campus-mcp" cmd /k "%~dp0start-mcp.bat"
echo Backend  -> http://127.0.0.1:8000/docs
echo Frontend -> http://127.0.0.1:5173
echo MCP      -> http://127.0.0.1:8001/mcp
echo Three new windows were opened. Keep them running.
pause
