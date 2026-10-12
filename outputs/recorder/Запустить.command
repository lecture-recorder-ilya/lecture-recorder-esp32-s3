#!/bin/zsh
TASK_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$TASK_ROOT"
echo 'Открой http://127.0.0.1:8767 в браузере. Запись работает независимо от этого окна.'
exec "$TASK_ROOT/work/esp-check-env/bin/python" "$TASK_ROOT/outputs/recorder/app_server.py"
