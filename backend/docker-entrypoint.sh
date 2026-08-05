#!/bin/sh
set -e

study_log_dir="${STUDY_LOG_DIR:-/app/study_logs}"

if [ "$(id -u)" = "0" ]; then
  mkdir -p "$study_log_dir"
  chown -R app:app "$study_log_dir"
  exec runuser -u app -- "$@"
fi

exec "$@"
