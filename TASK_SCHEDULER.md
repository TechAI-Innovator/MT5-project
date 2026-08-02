# Task Scheduler setup (VPS) — avoid dual instances

## Rule
Run the monitor from EITHER:
- a terminal (`.\run_monitor.bat`), OR
- Task Scheduler
NEVER both at the same time.

## Recommended Task Scheduler settings
1. Action: Start a program
   - Program: `C:\Users\Administrator\Desktop\MT5-project-main\run_monitor.bat`
   - Start in: `C:\Users\Administrator\Desktop\MT5-project-main`
2. Settings tab:
   - [x] If the task is already running: **Do not start a new instance**
   - [ ] Uncheck "Stop the task if it runs longer than..."
3. Before enabling the task: close any terminal that is already running the monitor
4. After a bad dual-run, kill leftover Python:
   `Stop-Process -Name python -Force -ErrorAction SilentlyContinue`

The app now refuses to start a second copy (see `logs\monitor.lock`).
