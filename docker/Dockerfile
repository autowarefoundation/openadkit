FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    mkdocs-material \
    mkdocs-awesome-pages-plugin \
    mkdocs-exclude \
    mkdocs-macros-plugin \
    mkdocs-same-dir \
    pymdown-extensions \
    python-markdown-math \
    mdx-truly-sane-lists \
    plantuml-markdown \
    mkdocs-mermaid2-plugin

EXPOSE 8000

CMD ["mkdocs", "serve", "--dev-addr=0.0.0.0:8000"]
