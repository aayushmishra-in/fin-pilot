#!/bin/sh
set -eu

port="${PORT:-10000}"

uv run uvicorn app.main:app --host 0.0.0.0 --port "$port" &
api_pid=$!
uv run arq app.worker.WorkerSettings &
worker_pid=$!

stop_children() {
  kill "$api_pid" "$worker_pid" 2>/dev/null || true
  wait "$api_pid" 2>/dev/null || true
  wait "$worker_pid" 2>/dev/null || true
}

trap 'exit 0' INT TERM
trap stop_children EXIT

while kill -0 "$api_pid" 2>/dev/null && kill -0 "$worker_pid" 2>/dev/null; do
  sleep 1
done

echo "FinPilot API or worker stopped; exiting so the host can restart the service." >&2
exit 1
