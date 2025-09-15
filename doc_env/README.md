# Openadkit: Containerized MkDocs Development

This document explains how to set up a containerized development environment for MkDocs in the Openadkit project using Docker. The `docker/Dockerfile` is designed to replicate the dependencies and configuration used in the project's GitHub Actions workflow, ensuring consistency between local development and CI/CD environments.

## TL;DR

In the Openadkit project root directory:

```bash
docker build -f docker/Dockerfile -t mkdocs-dev .
```

Then run the development server:

```bash
docker run -it --rm -p 8000:8000 -v $(pwd):/app mkdocs-dev
```

Access the MkDocs development server at `http://localhost:8000`.

## Prerequisites

- **Docker**: Ensure Docker is installed on your system. Download and install from [docker.com](https://www.docker.com/get-started).
- **Project Files**: The project root must contain `mkdocs.yml` and a `docs/` directory with Markdown files.

## Dockerfile Overview

The `docker/Dockerfile` sets up a Python 3.11 environment with all required MkDocs plugins, matching the GitHub Actions configuration. It includes:

- Base image: `python:3.11-slim`
- Installed dependencies:
  - `mkdocs-material`
  - `mkdocs-awesome-pages-plugin`
  - `mkdocs-exclude`
  - `mkdocs-macros-plugin`
  - `mkdocs-same-dir`
  - `pymdown-extensions`
  - `python-markdown-math`
  - `mdx-truly-sane-lists`
  - `plantuml-markdown`
  - `mkdocs-mermaid2-plugin`
- Working directory: `/app`
- Exposed port: `8000` for the MkDocs development server

## Building the Docker Image

To build the Docker image, run the following command in the project root directory:

```bash
docker build -f docker/Dockerfile -t mkdocs-dev .
```

### Parameters Explained:
- `-f docker/Dockerfile`: Specifies the path to the Dockerfile located in the `docker/` directory.
- `-t mkdocs-dev`: Tags the image as `mkdocs-dev` for easy reference.
- `.`: Sets the build context to the project root, including `mkdocs.yml` and `docs/` for copying into the image.

### Notes:
- The build context (`.`) must include `mkdocs.yml` and `docs/` to match the `COPY` instructions in the Dockerfile.
- Use a `.dockerignore` file to exclude unnecessary files (e.g., `site/`, `tmp/`) to reduce build time. Example `.dockerignore`:
  ```
  .github/
  deployments/
  ```

## Running the Development Server

To start the MkDocs development server, run:

```bash
docker run -it --rm -p 8000:8000 -v $(pwd):/app mkdocs-dev
```

### Parameters Explained:
- `-it`: Runs the container in interactive mode with a pseudo-TTY, allowing real-time logs.
- `--rm`: Automatically removes the container when it exits, keeping your system clean.
- `-p 8000:8000`: Maps port `8000` on the host to port `8000` in the container, enabling access to the MkDocs server at `http://localhost:8000`.
- `-v $(pwd):/app`: Mounts the current directory to `/app` in the container, enabling live reloading when editing Markdown files.
- `mkdocs-dev`: The name of the Docker image built earlier.

### Accessing the Server:
- Open a browser and navigate to `http://localhost:8000` to view the live MkDocs site.
- Changes to files in `docs/` or `mkdocs.yml` will trigger automatic reloading.

## Building the Static Site

To generate the static site (e.g., for testing the production build), run:

```bash
docker run -it --rm -v $(pwd):/app mkdocs-dev mkdocs build
```

- This command generates the static site in the `site/` directory, matching the output of the GitHub Actions workflow.
- The `-v $(pwd):/app` ensures the generated `site/` directory is saved to your local filesystem.


## Additional Notes

- **Consistency with CI/CD**: The Dockerfile mirrors the dependencies in the GitHub Actions workflow, ensuring identical behavior between local development and production builds.
- **Customizing Plugins**: If additional MkDocs plugins are needed, update both the `Dockerfile` and `mkdocs.yml` to maintain consistency.
- **Cleaning Up**: Remove unused images and containers with `docker system prune` to free up disk space.
- **Documentation**: Refer to `docs/dev/index.md` for additional development environment details.

For further assistance, consult the main `README.md` or open an issue in the Openadkit repository.