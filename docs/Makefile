# Makefile for Open AD Kit documentation
# Installs required MkDocs packages and serves documentation

# Repo root is one level above this Makefile (docs/)
REPO_ROOT := $(shell cd .. && pwd)
OPENADKIT_CLI_REF := $(shell git -C "$(REPO_ROOT)" rev-parse HEAD)
DOCS_CONTAINER_ENV := -e OPENADKIT_CLI_REF=$(OPENADKIT_CLI_REF)

.PHONY: help prepare prepare-if-missing serve build clean

# Default target
help:
	@echo "Open AD Kit Documentation - Available commands:"
	@echo "  make prepare      Prepare Mkdocs development container"
	@echo "  make prepare-if-missing  Reuse local image if present, otherwise build it"
	@echo "  make serve        Start development server on the built container"
	@echo "  make build        Build static documentation"
	@echo "  make clean        Clean build artifacts"

# Serve documentation locally
serve: prepare-if-missing
	docker run --rm -p 8000:8000 -v $(REPO_ROOT):/app --user $$(id -u):$$(id -g) $(DOCS_CONTAINER_ENV) -e NO_MKDOCS_2_WARNING=1 mkdocs-dev

# Build static documentation
build: prepare-if-missing
	docker run --rm -v $(REPO_ROOT):/app --user $$(id -u):$$(id -g) $(DOCS_CONTAINER_ENV) -e NO_MKDOCS_2_WARNING=1 mkdocs-dev mkdocs build

# Clean build artifacts
clean:
	rm -rf $(REPO_ROOT)/site

# Install mkdocs dependencies
prepare:
	docker build -t mkdocs-dev .

# Reuse an existing image when offline or when rebuilding is unnecessary
prepare-if-missing:
	@if docker image inspect mkdocs-dev >/dev/null 2>&1; then \
		echo "Using existing mkdocs-dev image"; \
	else \
		docker build -t mkdocs-dev .; \
	fi
