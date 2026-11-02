# Reproducibility image for PROBATIO: Python checkers, the JavaScript verifier and a
# pinned Lean 4 toolchain for the formal-proof checker.
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends git jq nodejs curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN useradd -m probatio
USER probatio
ENV PATH="/home/probatio/.elan/bin:/home/probatio/.local/bin:${PATH}"
RUN curl -sSfL https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -o /tmp/elan-init.sh \
    && sh /tmp/elan-init.sh -y --default-toolchain leanprover/lean4:v4.15.0 && rm /tmp/elan-init.sh
WORKDIR /home/probatio/probatio
COPY --chown=probatio . .
RUN pip install --user --no-cache-dir -e ".[dev,sign]"
CMD ["bash", "scripts/reproduce.sh"]
