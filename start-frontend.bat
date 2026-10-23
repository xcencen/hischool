@echo off
REM Start Vue3 dev server (Vite) on 127.0.0.1:5173
cd /d "%~dp0frontend"
echo Starting frontend at http://127.0.0.1:5173 ...
npm run dev
