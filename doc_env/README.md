# Open AD Kit: Containerized MkDocs Development

This document explains how to set up a containerized development environment for MkDocs in the Open AD Kit project using Docker and Makefile. The `doc_env/Dockerfile` and `Makefile` are designed to replicate the dependencies and configuration used in the project's GitHub Actions workflow, ensuring consistency between local development and CI/CD environments.

## TL;DR

In the Open AD Kit project **root directory**:

```bash
make prepare
make serve
```

Access the MkDocs development server at `http://localhost:8000/openadkit/`. To build the static site:

```bash
make build
```

## Prerequisites

- **Docker**: Ensure Docker is installed on your system. Download and install from [docker.com](https://www.docker.com/get-started).
- **Project Files**: The project root must contain `mkdocs.yaml` and a `docs/` directory with Markdown files.

## Makefile Overview

The `Makefile` simplifies common tasks for managing the MkDocs environment. Available commands:

- `make prepare`: Rebuilds the Docker image with required MkDocs dependencies.
- `make prepare-if-missing`: Reuses an existing `mkdocs-dev` image if present, otherwise builds it.
- `make serve`: Starts the MkDocs development server at `http://localhost:8000/openadkit/`.
- `make build`: Generates the static site in the `site/` directory with correct permissions.
- `make clean`: Removes the `site/` directory to clean up build artifacts.
- `make help`: Displays available commands.

Run `make help` to see all options.

## Setup and Usage

1. **Prepare the Docker Image**

   Run the following command to build the Docker image:

   ```bash
   make prepare
   ```

    This builds the `mkdocs-dev` image using the `doc_env/Dockerfile`, which includes:
    - Base image: `python:3.11-slim`
    - Installed MkDocs plugins: `mkdocs-material`, `mkdocs-awesome-pages-plugin`, `mkdocs-exclude`, `mkdocs-macros-plugin`, `pymdown-extensions`, `python-markdown-math`, `mdx-truly-sane-lists`, `plantuml-markdown`
    - Working directory: `/app`
    - Exposed port: `8000`

    Use `make prepare-if-missing` only when you intentionally want to reuse an existing local image, such as during offline verification.

2. **Run the Development Server**

   Start the MkDocs development server with:

   ```bash
   make serve
   ```

   - Opens `http://localhost:8000/openadkit/` in your browser to view the live site.
   - Changes to `docs/` or `mkdocs.yaml` trigger automatic reloading.
   - The current directory is mounted to `/app` in the container for live updates.

3. **Build the Static Site**

   Generate the static site with:

   ```bash
   make build
   ```

   - Outputs the static site to the `site/` directory.
   - Ensures file permissions match the host user, avoiding root ownership issues.
   - Matches the output of the GitHub Actions workflow.

4. **Clean Up**

   Remove the `site/` directory with:

   ```bash
   make clean
   ```

## Notes

- **File Permissions**: The `make build` command uses `--user $(id -u):$(id -g)` to ensure the `site/` directory has the same ownership as your host user, avoiding permission issues on Linux systems.
- **Customizing Plugins**: Update both `doc_env/Dockerfile` and `mkdocs.yaml` if additional MkDocs plugins are needed.
- **Cleaning Up Docker**: Use `docker system prune` to remove unused images and containers.
- **Documentation Source**: The published documentation lives under `docs/` and is configured by `mkdocs.yaml`.

## Troubleshooting

- **Permission Issues**: If the `site/` directory has incorrect permissions, ensure `make build` is used instead of directly running `docker run ... mkdocs build`.
- **Port Conflicts**: If port `8000` is in use, stop other services or change the port mapping (e.g., `-p 8001:8000` in the `make serve` command by editing the `Makefile`).
- **Prepare Fails During Package Download**: If Docker cannot reach PyPI while building `mkdocs-dev`, rerun `make prepare` once network access is available. If you already have a suitable local image and only need to test docs content, use `make prepare-if-missing`.

For further assistance, consult the main `README.md` or open an issue in the Open AD Kit repository.
