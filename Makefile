# Makefile for Openadkit Document
# Installs required MkDocs packages and serves documentation

.PHONY: help prepare serve build clean

# Default target
help:
	@echo "Openadkit Documentation - Available commands:"
	@echo "  make prepare      Prepare Mkdocs development container"
	@echo "  make serve        Start development server on the built container"
	@echo "  make build        Build static documentation"
	@echo "  make clean        Clean build artifacts"

# Serve documentation locally
serve:
	docker run -it --rm -p 8000:8000 -v $$(pwd):/app mkdocs-dev

# Build static documentation
build:
	docker run -it --rm -v $$(pwd):/app --user $$(id -u):$$(id -g) mkdocs-dev mkdocs build

# Clean build artifacts
clean:
	rm -rf site/

# Install mkdocs dependencies
prepare:
	docker build -f doc_env/Dockerfile -t mkdocs-dev .
