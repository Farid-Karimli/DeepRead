SHELL := /bin/bash
export PATH := $(HOME)/.local/bin:/opt/homebrew/bin:/usr/local/bin:$(PATH)

# Repo root = directory of this Makefile (not $(CURDIR), which is your shell cwd).
ROOT_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
BACKEND_DIR := $(ROOT_DIR)/backend
FRONTEND_DIR := $(ROOT_DIR)/frontend
LOG_DIR := $(ROOT_DIR)/logs
PID_DIR := $(ROOT_DIR)/.pids

BACKEND_PORT := 8000
FRONTEND_PORT := 5173

BACKEND_LOG := $(LOG_DIR)/backend.log
CELERY_LOG := $(LOG_DIR)/celery.log
FRONTEND_LOG := $(LOG_DIR)/frontend.log

BACKEND_PID := $(PID_DIR)/backend.pid
CELERY_PID := $(PID_DIR)/celery.pid
FRONTEND_PID := $(PID_DIR)/frontend.pid

.PHONY: help up down restart status logs logs-backend logs-celery logs-frontend clean-logs

help:
	@echo "Targets:"
	@echo "  make up          Start frontend, backend, and celery worker"
	@echo "  make down        Stop services and free ports $(BACKEND_PORT) / $(FRONTEND_PORT)"
	@echo "  make restart     Restart all services"
	@echo "  make status      Show service status"
	@echo "  make logs        Tail all logs"
	@echo "  make logs-backend|logs-celery|logs-frontend"
	@echo "  make clean-logs  Remove logs and pid files"

# Port $(1), label $(2) — must stay on one logical recipe (backslash-continued) so one shell runs it.
# Frees stuck uvicorn --reload children that still hold the port after the parent PID died.
up:
	@mkdir -p "$(LOG_DIR)" "$(PID_DIR)"
	@if [ -f "$(BACKEND_PID)" ] && kill -0 "$$(cat "$(BACKEND_PID)")" 2>/dev/null; then \
		echo "backend already running (pid $$(cat "$(BACKEND_PID)"))"; \
	else \
		echo "starting backend..."; \
		rm -f "$(BACKEND_PID)"; \
		if command -v lsof >/dev/null 2>&1; then \
			pids="$$(lsof -tiTCP:$(BACKEND_PORT) -sTCP:LISTEN 2>/dev/null | sort -u)"; \
			if [ -n "$$pids" ]; then \
				echo "backend: freeing port $(BACKEND_PORT) (pids: $$pids)"; \
				kill $$pids 2>/dev/null || true; \
				sleep 0.5; \
				pids="$$(lsof -tiTCP:$(BACKEND_PORT) -sTCP:LISTEN 2>/dev/null | sort -u)"; \
				[ -n "$$pids" ] && ( echo "backend: force kill: $$pids"; kill -9 $$pids 2>/dev/null || true; sleep 0.3 ); \
			fi; \
		fi; \
		( cd "$(BACKEND_DIR)" && \
		  { nohup uv run python -m uvicorn src.server:app \
		    --host 127.0.0.1 --port $(BACKEND_PORT) --reload \
		    >> "$(BACKEND_LOG)" 2>&1 & echo $$! > "$(BACKEND_PID)"; } ); \
		sleep 0.6; \
		if [ -f "$(BACKEND_PID)" ] && kill -0 "$$(cat "$(BACKEND_PID)")" 2>/dev/null; then \
			echo "  backend pid $$(cat "$(BACKEND_PID)") (port $(BACKEND_PORT))"; \
		else \
			echo "  backend failed — see $(BACKEND_LOG)"; \
		fi; \
	fi
	@if [ -f "$(CELERY_PID)" ] && kill -0 "$$(cat "$(CELERY_PID)")" 2>/dev/null; then \
		echo "celery already running (pid $$(cat "$(CELERY_PID)"))"; \
	else \
		echo "starting celery worker..."; \
		rm -f "$(CELERY_PID)"; \
		( cd "$(BACKEND_DIR)" && \
		  { nohup uv run python -m celery -A src.server.celery worker --loglevel=info \
		    >> "$(CELERY_LOG)" 2>&1 & echo $$! > "$(CELERY_PID)"; } ); \
		sleep 0.6; \
		if [ -f "$(CELERY_PID)" ] && kill -0 "$$(cat "$(CELERY_PID)")" 2>/dev/null; then \
			echo "  celery pid $$(cat "$(CELERY_PID)")"; \
		else \
			echo "  celery failed — see $(CELERY_LOG)"; \
		fi; \
	fi
	@if [ -f "$(FRONTEND_PID)" ] && kill -0 "$$(cat "$(FRONTEND_PID)")" 2>/dev/null; then \
		echo "frontend already running (pid $$(cat "$(FRONTEND_PID)"))"; \
	else \
		echo "starting frontend..."; \
		rm -f "$(FRONTEND_PID)"; \
		if command -v lsof >/dev/null 2>&1; then \
			pids="$$(lsof -tiTCP:$(FRONTEND_PORT) -sTCP:LISTEN 2>/dev/null | sort -u)"; \
			if [ -n "$$pids" ]; then \
				echo "frontend: freeing port $(FRONTEND_PORT) (pids: $$pids)"; \
				kill $$pids 2>/dev/null || true; \
				sleep 0.5; \
				pids="$$(lsof -tiTCP:$(FRONTEND_PORT) -sTCP:LISTEN 2>/dev/null | sort -u)"; \
				[ -n "$$pids" ] && ( echo "frontend: force kill: $$pids"; kill -9 $$pids 2>/dev/null || true; sleep 0.3 ); \
			fi; \
		fi; \
		( cd "$(FRONTEND_DIR)" && \
		  { nohup npm run dev >> "$(FRONTEND_LOG)" 2>&1 & echo $$! > "$(FRONTEND_PID)"; } ); \
		sleep 0.6; \
		if [ -f "$(FRONTEND_PID)" ] && kill -0 "$$(cat "$(FRONTEND_PID)")" 2>/dev/null; then \
			echo "  frontend pid $$(cat "$(FRONTEND_PID)") (Vite ~$(FRONTEND_PORT))"; \
		else \
			echo "  frontend failed — see $(FRONTEND_LOG)"; \
		fi; \
	fi
	@echo "all services started (or already running)."
	@$(MAKE) --no-print-directory status

down:
	@echo "stopping services (pid files + freeing ports)..."
	@for svc in backend celery frontend; do \
		pid_file="$(PID_DIR)/$$svc.pid"; \
		if [ -f "$$pid_file" ] && kill -0 "$$(cat "$$pid_file")" 2>/dev/null; then \
			echo "stopping $$svc (pid $$(cat "$$pid_file"))"; \
			kill "$$(cat "$$pid_file")" 2>/dev/null || true; \
		fi; \
		rm -f "$$pid_file"; \
	done
	@sleep 0.4
	@if command -v lsof >/dev/null 2>&1; then \
		for port in $(BACKEND_PORT) $(FRONTEND_PORT); do \
			pids="$$(lsof -tiTCP:$$port -sTCP:LISTEN 2>/dev/null | sort -u)"; \
			if [ -n "$$pids" ]; then \
				echo "freeing port $$port: $$pids"; \
				kill $$pids 2>/dev/null || true; \
				sleep 0.4; \
				pids="$$(lsof -tiTCP:$$port -sTCP:LISTEN 2>/dev/null | sort -u)"; \
				[ -n "$$pids" ] && kill -9 $$pids 2>/dev/null || true; \
			fi; \
		done; \
	fi
	@echo "stop completed."

restart: down up

status:
	@for svc in backend celery frontend; do \
		pid_file="$(PID_DIR)/$$svc.pid"; \
		if [ -f "$$pid_file" ] && kill -0 "$$(cat "$$pid_file")" 2>/dev/null; then \
			echo "$$svc: running (pid $$(cat "$$pid_file"))"; \
		else \
			echo "$$svc: stopped"; \
		fi; \
	done

logs:
	@touch "$(BACKEND_LOG)" "$(CELERY_LOG)" "$(FRONTEND_LOG)"
	@tail -f "$(BACKEND_LOG)" "$(CELERY_LOG)" "$(FRONTEND_LOG)"

logs-backend:
	@touch "$(BACKEND_LOG)"
	@tail -f "$(BACKEND_LOG)"

logs-celery:
	@touch "$(CELERY_LOG)"
	@tail -f "$(CELERY_LOG)"

logs-frontend:
	@touch "$(FRONTEND_LOG)"
	@tail -f "$(FRONTEND_LOG)"

clean-logs:
	@rm -f "$(BACKEND_LOG)" "$(CELERY_LOG)" "$(FRONTEND_LOG)"
	@rm -f "$(BACKEND_PID)" "$(CELERY_PID)" "$(FRONTEND_PID)"
	@echo "logs and pid files removed."
