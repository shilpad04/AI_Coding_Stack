---
name: podman-k8s-devops
description: >-
  Containerization and orchestration skill for Podman (local development) and
  Kubernetes (production). Enforces rootless Podman workflows, lean multi-stage builds,
  and cloud-native K8s manifests (resource limits, health probes, non-root securityContext).
---

# Podman & Kubernetes DevOps Skill

Use this skill when creating or modifying files under `infrastructure/` — `Containerfile`, `compose.yaml`, or the Helm chart in `infrastructure/helm/`.

---

## 1. Local Development with Podman (Rootless)

Podman runs daemonless and rootless by default. Adhere to these guidelines:

### Containerfile Best Practices

- **Prefer `Containerfile`**: Standard Podman naming (use `Containerfile` or symlink `Dockerfile`).
- **Volume Mounts (`:Z` flag)**: On Linux / SELinux environments, always append `:Z` to volume bind-mounts so rootless Podman has write access:
  ```yaml
  volumes:
    - ./:/app:Z
  ```
- **Hot-Reloading in Compose**: When running local dev servers (e.g. Vite, FastAPI `uvicorn --reload`), expose host ports and bind mount local directories.
- **Port Mapping**: Do not bind privileged ports (<1024) directly in rootless mode; map to unprivileged ports (e.g., `8080:8080`, `3000:3000`).

---

## 2. Multi-Stage Production Container Builds

Never ship bloated development containers containing compilers, package managers, or temporary test dependencies to production.

### Multi-Stage Python Template:

```dockerfile
# ─── Stage 1: Build & Dependencies ───
FROM python:3.12-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ─── Stage 2: Final Minimal Runtime ───
FROM python:3.12-slim AS runner
WORKDIR /app
# Create unprivileged system user
RUN groupadd -g 10001 appgroup && useradd -u 10001 -g appgroup -s /bin/sh appuser
COPY --from=builder /root/.local /home/appuser/.local
COPY --chown=appuser:appgroup src/ ./src/

ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "src.main"]
```

### Always Add `.containerignore` / `.dockerignore`:

Exclude `.git`, `__pycache__`, `.venv`, `.pytest_cache`, `.ai`, `node_modules`, `tests`, `*.log`.

---

## 3. Enterprise Kubernetes Manifest Standards

When writing Kubernetes YAML files, always implement production hygiene:

### 1. Explicit Resource Requests & Limits

Prevent cluster node starvation and runaway memory leaks:

```yaml
resources:
  requests:
    cpu: "100m"
    memory: "128Mi"
  limits:
    cpu: "500m"
    memory: "512Mi"
```

### 2. Mandatory Health Probes

```yaml
livenessProbe:
  httpGet:
    path: /healthz
    port: 8000
  initialDelaySeconds: 15
  periodSeconds: 20
readinessProbe:
  httpGet:
    path: /ready
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 10
```

### 3. Hardened Security Context

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 10001
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop:
      - ALL
```

### 4. Dev-to-Prod Parity

- Keep configuration in `ConfigMap` and secrets in `Secret`.
- Ensure environment variable names in `compose.yaml` match the `envFrom` / `configMapRef` keys in the Helm templates.
