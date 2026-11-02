# Reproducibility image for PROBATIO
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends git jq nodejs \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /probatio
COPY . .
RUN pip install --no-cache-dir numpy matplotlib pytest cryptography && pip install --no-cache-dir -e .
CMD ["bash", "scripts/reproduce.sh"]
