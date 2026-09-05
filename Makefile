# Realtime monitoring stack — developer commands.
# Requires: python3, and (for setup only) nothing else; docker for promtool/deploy.
PY   ?= python3
VENV ?= .venv
BIN  := $(VENV)/bin
STACK := $(BIN)/monitoring-stack

DOCKER_IMAGE ?= monitoring-stack:local
DOCKER_RUN  := docker run --rm -v "$$PWD":/app --user "$$(id -u):$$(id -g)"
# For commands that talk to the daemon (deploy/status/down, integration): mount
# the checkout at its own host path (the daemon resolves bind mounts against
# host paths), share the docker socket, use host networking for health checks,
# and use the docker group gid so the socket is reachable.
DOCKER_RUN_STACK := docker run --rm --network host -v "$$PWD":"$$PWD" -w "$$PWD" \
        -v /var/run/docker.sock:/var/run/docker.sock \
        --user "$$(id -u):$$(getent group docker | cut -d: -f3)"

.PHONY: help setup test lint lint-fix config validate promtool check deploy down status logs \
        docker-build docker-config docker-validate docker-test docker-deploy docker-status \
        docker-down docker-tox docker-tox-integration

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
	# --entrypoint is required: the prom/alertmanager images default to their daemon binaries
	docker run --rm -v "$$PWD/generated/prometheus:/etc/prometheus" --entrypoint promtool prom/prometheus:v2.55.1 check config /etc/prometheus/prometheus.yml
	docker run --rm -v "$$PWD/generated/prometheus:/etc/prometheus" --entrypoint promtool prom/prometheus:v2.55.1 check rules /etc/prometheus/rules/recording.yml /etc/prometheus/rules/alerts.yml
	docker run --rm -v "$$PWD/generated/alertmanager:/etc/alertmanager" --entrypoint amtool prom/alertmanager:v0.27.0 check-config /etc/alertmanager/alertmanager.yml

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

docker-build:    ## Build the CLI Docker image (hardened runtime target)
	docker build -t $(DOCKER_IMAGE) .

docker-config:   ## Generate configs via the CLI Docker image
	$(DOCKER_RUN) $(DOCKER_IMAGE) config

docker-validate: ## Validate generated configs via the CLI Docker image
	$(DOCKER_RUN) $(DOCKER_IMAGE) validate

docker-test:     ## Build the dev image and run pytest inside it
	docker build --target dev -t monitoring-stack:dev .
	$(DOCKER_RUN) monitoring-stack:dev

docker-deploy:   ## Deploy the stack via the CLI Docker image (needs docker socket)
	$(DOCKER_RUN_STACK) $(DOCKER_IMAGE) deploy

docker-status:   ## Container status + health checks via the CLI Docker image
	$(DOCKER_RUN_STACK) $(DOCKER_IMAGE) status

docker-down:     ## Stop the stack via the CLI Docker image
	$(DOCKER_RUN_STACK) $(DOCKER_IMAGE) down

docker-tox:      ## Run tox (test/lint/validate envs) inside the dev image
	$(DOCKER_RUN) monitoring-stack:dev tox

docker-tox-integration: ## Run tox -e integration (stack must be deployed)
	$(DOCKER_RUN_STACK) -e MONITORING_STACK_INTEGRATION=1 monitoring-stack:dev tox -e integration