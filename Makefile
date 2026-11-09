# Phase 0 in one line:  make tools db setup scan
OSV_VERSION := $(shell awk '/osv_scanner_version/ {gsub(/"/,"",$$2); print $$2}' targets.yaml)
OS   := $(shell uname -s | tr A-Z a-z)
ARCH := $(shell uname -m | sed 's/x86_64/amd64/; s/aarch64/arm64/')

.PHONY: tools db setup baseline scan stats test

tools:            ## download the pinned osv-scanner binary into .work/bin
	mkdir -p .work/bin
	curl -sSfL -o .work/bin/osv-scanner \
	  https://github.com/google/osv-scanner/releases/download/v$(OSV_VERSION)/osv-scanner_$(OS)_$(ARCH)
	chmod +x .work/bin/osv-scanner && .work/bin/osv-scanner --version

db:               ## build the pinned offline advisory DB
	uv run rt build-db

setup:            ## clone targets, build venvs, freeze runtime locks
	uv run rt setup all

baseline:         ## run each target's test suite unmodified
	uv run rt baseline all

scan:             ## scan locks -> data/raw/*.osv.json + data/findings.jsonl
	uv run rt scan

stats:
	uv run rt stats

test:
	uv run pytest -q
