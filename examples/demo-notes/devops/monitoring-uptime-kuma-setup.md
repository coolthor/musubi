---
title: "Uptime Kuma: Self-Hosted Monitoring in 5 Minutes"
date: "2026-02-28"
tags: ["monitoring", "docker", "deploy", "security"]
---

## What It Monitors

HTTP endpoints, TCP ports, DNS resolution, Docker containers, and
database connectivity. Sends alerts via Telegram, Discord, Slack,
email, or webhooks.

## Docker Setup

```bash
docker run -d --name uptime-kuma \
  -p 3001:3001 \
  -v uptime-kuma:/app/data \
  --restart unless-stopped \
  louislam/uptime-kuma:1
```

## Production Tips

- Put behind a reverse proxy (Cloudflare Tunnel or nginx) for HTTPS
- Set check interval to 60s minimum — don't hammer your own services
- Use status pages for external visibility
- Monitor the monitor: if the Docker host goes down, Uptime Kuma
  goes with it. Consider a cheap external ping service as backup.

## Alert Fatigue

Start with critical endpoints only (health check, login page). Add
more monitors gradually. Too many alerts = everyone ignores them.
