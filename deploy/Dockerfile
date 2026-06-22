# Container image for the looptight persistent daemon.
#
#   docker build -f deploy/Dockerfile -t looptight-daemon .
#   docker run -d --restart unless-stopped \
#     -e ANTHROPIC_API_KEY=sk-ant-... \
#     -v /path/to/your/repo:/workspace \
#     looptight-daemon
#
# The daemon spawns the coding-agent CLI as a child process, so that CLI must be
# installed in this image. The line below is a placeholder: replace it with the
# install step for your agent (e.g. Claude Code) — see docs/daemon.md. git is
# required for checkpoints, worktrees, and pushing.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# >>> install your coding-agent CLI here, e.g. Claude Code <<<
# RUN curl -fsSL https://claude.ai/install.sh | sh    # illustrative

COPY . /src
RUN pip install --no-cache-dir /src

# Mount the repo to improve at /workspace (must contain .looptight.toml).
WORKDIR /workspace
ENTRYPOINT ["looptight", "daemon", "--headless", "--push"]
CMD ["--agent", "claude", "--model", "opus", "--workers", "4"]
