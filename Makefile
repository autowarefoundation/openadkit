# Makefile for Open AD Kit documentation
# Installs required MkDocs packages and serves documentation

.PHONY: help prepare prepare-if-missing serve build clean generate-release-notes

# Default target
help:
	@echo "Open AD Kit Documentation - Available commands:"
	@echo "  make prepare      Prepare Mkdocs development container"
	@echo "  make prepare-if-missing  Reuse local image if present, otherwise build it"
	@echo "  make serve        Start development server on the built container"
	@echo "  make build        Build static documentation"
	@echo "  make generate-release-notes  Refresh release notes from GitHub Releases"
	@echo "  make clean        Clean build artifacts"

# Serve documentation locally
serve: prepare-if-missing generate-release-notes
	docker run --rm -p 8000:8000 -v $$(pwd):/app -e NO_MKDOCS_2_WARNING=1 mkdocs-dev

# Refresh release notes from GitHub Releases (runs inside the docs container).
# Non-fatal: when offline or rate-limited, the site still builds — the
# Releases page is simply skipped until the next successful refresh.
generate-release-notes:
	@docker run --rm -v $$(pwd):/app --user $$(id -u):$$(id -g) -e GITHUB_TOKEN mkdocs-dev \
		python docs/scripts/generate_release_notes.py \
		|| echo "WARNING: could not refresh release notes (offline or rate-limited); continuing without them"

# Build static documentation
build: prepare-if-missing generate-release-notes
	docker run --rm -v $$(pwd):/app --user $$(id -u):$$(id -g) -e NO_MKDOCS_2_WARNING=1 mkdocs-dev mkdocs build

# Clean build artifacts
clean:
	rm -rf site/

# Install mkdocs dependencies
prepare:
	docker build -t mkdocs-dev docs

# Reuse an existing image when offline or when rebuilding is unnecessary
prepare-if-missing:
	@if docker image inspect mkdocs-dev >/dev/null 2>&1; then \
		echo "Using existing mkdocs-dev image"; \
	else \
		docker build -t mkdocs-dev docs; \
	fi
