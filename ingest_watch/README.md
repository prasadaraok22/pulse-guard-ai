# Log Watch Directory

Pulse Guard AI's background scheduler tails `*.log` files dropped into this
directory. Only newly-appended lines are ingested on each poll (offset tracking
+ rotation handling), then the anomaly engine runs and alerts fire.

## Enable continuous polling

```bash
# auto-start on boot
PULSE_POLL_ENABLED=true PULSE_POLL_INTERVAL_SECONDS=10 \
  uvicorn app.main:app --port 8100

# or control at runtime
curl -X POST localhost:8100/api/scheduler/start
curl      localhost:8100/api/scheduler/status
curl -X POST localhost:8100/api/scheduler/poll     # poll once now
curl -X POST localhost:8100/api/scheduler/stop
```

## Feed it logs

The filename (without extension) becomes the default service name:

```bash
# each appended line is picked up on the next poll
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ERROR [payment-svc] timeout" \
  >> ingest_watch/payment-svc.log
```

Live `*.log` files here are git-ignored.

