@echo off
REM Start FastMCP server on 127.0.0.1:8001/mcp
cd /d "%~dp0backend"
set PYTHONPATH=.
call .venv\Scripts\activate.bat
echo Starting MCP server at http://127.0.0.1:8001/mcp ...
python mcp_server.py
