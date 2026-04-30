# CORS configuration

The frontend (`TransitPulseWebsite`) calls this API directly from the browser. CORS preflights must be allowed for every origin that needs to reach the backend.

## Setting

`app/config.py` reads `CORS_ORIGINS` (comma-separated string) and feeds the list into `CORSMiddleware`.

```
CORS_ORIGINS=http://localhost:3000
```

For multiple origins:

```
CORS_ORIGINS=http://localhost:3000,https://transitpulse.example.com,https://staging.transitpulse.example.com
```

## Deployment checklist when adding a new frontend environment

1. Update `CORS_ORIGINS` in the target environment (e.g. ECS/Lambda env vars, `.env`, or your secret manager).
2. **Redeploy the backend** — middleware reads the value at startup; in-place env changes do not take effect until the process restarts.
3. Deploy the frontend pointing `NEXT_PUBLIC_API_BASE_URL` at this backend.
4. Hit the new frontend; if requests fail with `No 'Access-Control-Allow-Origin' header`, the backend was not redeployed.

## Local development

Default `CORS_ORIGINS=http://localhost:3000` is sufficient. Override only if running the frontend on a non-default port.
