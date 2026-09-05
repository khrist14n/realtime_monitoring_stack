# Realtime monitoring stack — developer commands.
# Requires: python3, and (for setup only) nothing else; docker for promtool/deploy.
PY   ?= python3
VENV ?= .venv
BIN  := $(VENV)/bin
STACK := $(BIN)/monitoring-stack

.PHONY: help setup test lint lint-fix config validate promtool check deploy down status logs

help:            ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

setup:           ## Create venv and install the package with dev/test deps
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -e ".[dev]"

test:            ## Run the pytest suite (no network/Docker needed)
	$(BIN)/pytest

lint:            ## Ruff lint + format check
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

lint-fix:        ## Auto-fix lint issues and reformat
	$(BIN)/ruff check . --fix
	$(BIN)/ruff format .

config:          ## Regenerate all configs into generated/
	$(STACK) config

validate:        ## Validate generated configs (YAML/JSON, refs, PagerDuty key)
	$(STACK) validate

promtool:        ## Validate PromQL + Alertmanager configs with the real toolchain (Docker)
	docker run --rm -v "$$PWD/generated/prometheus:/etc/prometheus" prom/prometheus:v2.55.1 promtool check config /etc/prometheus/prometheus.yml
	docker run --rm -v "$$PWD/generated/prometheus:/etc/prometheus" prom/prometheus:v2.55.1 promtool check rules /etc/prometheus/rules/recording.yml /etc/prometheus/rules/alerts.yml
	docker run --rm -v "$$PWD/generated/alertmanager:/etc/alertmanager" prom/alertmanager:v0.27.0 amtool check-config /etc/alertmanager/alertmanager.yml

check:           ## Health-check a running stack
	$(STACK) check

deploy:          ## Generate configs, start the stack, run health checks
	$(STACK) deploy

down:            ## Stop the stack
	$(STACK) down

status:          ## Container status + health checks
	$(STACK) status

logs:            ## Tail logs (usage: make logs SERVICE=prometheus)
	$(STACK) logs $(SERVICE)