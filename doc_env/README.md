# Openadkit: Containerized MkDocs Development

This document explains how to set up a containerized development environment for MkDocs in the Openadkit project using Docker and Makefile. The `doc_env/Dockerfile` and `Makefile` are designed to replicate the dependencies and configuration used in the project's GitHub Actions workflow, ensuring consistency between local development and CI/CD environments.

## TL;DR

In the Openadkit project **root directory**:

```bash
make prepare
make serve
```

Access the MkDocs development server at `http://localhost:8000`. To build the static site:

```bash
make build
```

## Prerequisites

- **Docker**: Ensure Docker is installed on your system. Download and install from [docker.com](https://www.docker.com/get-started).
- **Project Files**: The project root must contain `mkdocs.yaml` and a `docs/` directory with Markdown files.

## Makefile Overview

The `Makefile` simplifies common tasks for managing the MkDocs environment. Available commands:

- `make prepare`: Builds the Docker image with required MkDocs dependencies.
- `make serve`: Starts the MkDocs development server at `http://localhost:8000`.
- `make build`: Generates the static site in the `site/` directory with correct permissions.
- `make clean`: Removes the `site/` directory to clean up build artifacts.
- `make help`: Displays available commands.

Run `make help` to see all options.

## Setup and Usage

1. **Build the Docker Image**

   Run the following command to build the Docker image:

   ```bash
   make prepare
   ```

   This builds the `mkdocs-dev` image using the `doc_env/Dockerfile`, which includes:
   - Base image: `python:3.11-slim`
   - Installed MkDocs plugins: `mkdocs-material`, `mkdocs-awesome-pages-plugin`, `mkdocs-exclude`, `mkdocs-macros-plugin`, `mkdocs-same-dir`, `pymdown-extensions`, `python-markdown-math`, `mdx-truly-sane-lists`, `plantuml-markdown`, `mkdocs-mermaid2-plugin`
   - Working directory: `/app`
   - Exposed port: `8000`

2. **Run the Development Server**

   Start the MkDocs development server with:

   ```bash
   make serve
   ```

   - Opens `http://localhost:8000` in your browser to view the live site.
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
- **Optimizing Builds**: Use a `.dockerignore` file to exclude unnecessary files (e.g., `site/`, `.github/`) to reduce build time. Example `.dockerignore`:
  ```
  .github/
  deployments/
  site/
  ```
- **Cleaning Up Docker**: Use `docker system prune` to remove unused images and containers.
- **Documentation**: Refer to `docs/dev/index.md` for additional development environment details.

## Troubleshooting

- **Permission Issues**: If the `site/` directory has incorrect permissions, ensure `make build` is used instead of directly running `docker run ... mkdocs build`.
- **Port Conflicts**: If port `8000` is in use, stop other services or change the port mapping (e.g., `-p 8001:8000` in the `make serve` command by editing the `Makefile`).

For further assistance, consult the main `README.md` or open an issue in the Openadkit repository.