# Research — AWS Lambda Web Adapter packaging

Source: user-provided summary in `extra-information.md` (item 3), with citations to the official AWS Lambda Web Adapter GitHub repo and AWS announcement. Captured here so the design doc has a self-contained reference.

## Pattern

The Web Adapter lets a normal HTTP server (FastAPI + uvicorn in our case) run inside a Lambda container without any handler code. The adapter binary is loaded as a Lambda extension; it receives Lambda invocation events, forwards them as ordinary HTTP requests to the local server, and translates responses back.

### Canonical Dockerfile

```dockerfile
FROM public.ecr.aws/docker/library/python:3.12-slim

COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.0.0 \
  /lambda-adapter /opt/extensions/lambda-adapter

WORKDIR /var/task

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

### Why this works

- **`COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:<ver> /lambda-adapter /opt/extensions/lambda-adapter`** — Lambda auto-loads anything in `/opt/extensions` as an external extension. The adapter image on ECR Public is multi-arch (`x86_64` and `arm64`).
- **`EXPOSE 8080`** — documentation only; doesn't configure Lambda networking. What actually matters is that the in-container web server binds to the same port the adapter probes (default 8080, overridable via `PORT`).
- **`CMD ["uvicorn", ...]`** — runs your normal HTTP server, not a Lambda handler. The adapter sits in front of it and translates events ↔ HTTP.

## Environment variables worth knowing

| Var | Purpose |
|---|---|
| `PORT` | Override the adapter's expected port. Default is 8080. Set this when your app reads `PORT` or when you want the contract explicit. |
| `AWS_LWA_INVOKE_MODE` | `buffered` (default) or `response_stream`. **Must match the Lambda Function URL invoke mode.** Mismatches break clients. |
| `AWS_LAMBDA_RUNTIME_API` | Lambda sets this in production; absent in local Docker. Useful as a way for the app to detect "am I running inside Lambda?" without code changes. |

## v1 design choices flowing from this

- **Pin the adapter version explicitly.** Use `:1.0.0` (or whatever the current stable release is), not implicit/latest. Regressions in the adapter would otherwise propagate via image rebuilds.
- **Default invoke mode = buffered.** v1 has no streaming responses; the default is correct.
- **Port = 8080** for both local and Lambda. No `PORT` env override needed.
- **Same image runs locally and in Lambda.** `docker-compose.yml` runs the same image as ECR; locally the adapter binary is present but inactive (Lambda env vars absent).
- **Local-only: Postgres is a separate compose service.** The image only contains the FastAPI app.

## Zip-package mode (NOT used)

If we ever switched away from container images (we won't in v1), the zip-package equivalent attaches the Web Adapter as a layer, sets `AWS_LAMBDA_EXEC_WRAPPER=/opt/bootstrap`, and points the Lambda handler at a startup script. Container-image mode is simpler and matches the Q7 decision.

## Sources cited by the user

- AWS Lambda Web Adapter GitHub repo (Dockerfile pattern, env vars, multi-arch ECR image).
- AWS announcement post (frameworks supported: Flask, Express, Spring Boot, Next.js; the adapter's purpose and behavior).

## Open items deferred to design

- **ECR repository** for our image — outside design scope; an ops decision for the deploy environment.
- **API Gateway HTTP API ↔ Lambda integration** — proxy `/{proxy+}` to the function. Standard pattern; no Web Adapter-specific quirks.
- **Cold-start latency** — accepted trade-off per Q7 implications.
