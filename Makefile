# Makefile for Open AD Kit documentation
# Installs required MkDocs packages and serves documentation

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
serve:
	docker run --rm -p 8000:8000 -v $$(pwd):/app mkdocs-dev

# Build static documentation
build:
	docker run --rm -v $$(pwd):/app --user $$(id -u):$$(id -g) mkdocs-dev mkdocs build

# Clean build artifacts
clean:
	rm -rf site/

# Install mkdocs dependencies
prepare:
	docker build -f doc_env/Dockerfile -t mkdocs-dev .

# Reuse an existing image when offline or when rebuilding is unnecessary
prepare-if-missing:
	@if docker image inspect mkdocs-dev >/dev/null 2>&1; then \
		echo "Using existing mkdocs-dev image"; \
	else \
		docker build -f doc_env/Dockerfile -t mkdocs-dev .; \
	fi
