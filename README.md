# stock-iot-collector

A small Kubernetes-ready stock data collector that treats each stock as a ThingsBoard virtual device.

By default, the data source is Polygon/Massive daily End-of-Day data: each stock has one OHLCV bar per U.S. market day, and the `price` telemetry value is the daily close. The collector runs once per hour to retry/sync the previous U.S. market weekday's daily data for all U.S. stocks, then publishes each stock to ThingsBoard by using the ThingsBoard MQTT Gateway API.

## Architecture

```text
Polygon / Massive API
        ↓
stock-iot-collector
        ↓ MQTT Gateway API
ThingsBoard Gateway Device
        ↓
stock.AAPL
stock.MSFT
stock.TSLA
```

## Default Behavior

- One collector = one ThingsBoard Gateway device.
- Each stock = one virtual device under that gateway.
- `config/stocks.yaml` defaults to `symbol: "*"`, so the collector uses Polygon's grouped daily endpoint for all U.S. stocks.
- The collector runs every hour by default: `POLL_INTERVAL_SECONDS=3600`.
- Daily mode fetches the previous U.S. market weekday in `America/New_York`: `DAILY_MARKET_DAYS_AGO=1`.
- Each stock gets one daily telemetry point per market day.
- `price` equals the daily close.
- Daily telemetry includes `open`, `high`, `low`, `close`, `price`, `volume`, `vwap`, and `transaction_count` when Polygon provides them.
- The ThingsBoard telemetry timestamp uses the market bar timestamp, not the publish time.
- `bar_timestamp_ms` is also included in the values for easier inspection.
- Set `BACKFILL_MARKET_DAYS` to run a one-time historical backfill, then exit.

Example:

```text
Collector runs: 2026-04-29 08:00 Asia/Taipei
Target market date: 2026-04-27 America/New_York
ThingsBoard telemetry timestamp: Polygon's daily bar timestamp
```

The default weekday logic skips weekends. It does not include a U.S. exchange holiday calendar, so a holiday may produce no data until the next successful run.

## Project Layout

```text
stock-iot-collector/
├── app/
│   ├── main.py
│   ├── collector.py
│   ├── config.py
│   ├── providers/
│   │   └── polygon.py
│   ├── sinks/
│   │   └── thingsboard.py
│   └── utils/
│       └── time_utils.py
├── config/
│   └── stocks.yaml
├── docker/
│   └── Dockerfile
├── k8s/
│   ├── namespace.yaml
│   ├── configmap.yaml
│   ├── secret.example.yaml
│   └── deployment.yaml
├── requirements.txt
└── README.md
```

## Local Setup

```bash
cd stock-iot-collector

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create required local environment variables:

```bash
export POLYGON_API_KEY="your_polygon_api_key"
export THINGSBOARD_MQTT_HOST="thingsboard.example.com"
export THINGSBOARD_MQTT_CA_CERT="/path/to/ca.crt"
export THINGSBOARD_MQTT_CLIENT_CERT="/path/to/client.crt"
export THINGSBOARD_MQTT_CLIENT_KEY="/path/to/client.key"
```

Run:

```bash
python -m app.main
```

## Docker

Build the image:

```bash
docker build -t stock-iot-collector:0.1.0 -f docker/Dockerfile .
```

Push the image to Docker Hub:

```bash
docker tag stock-iot-collector:0.1.0 cdlee/stock-iot-collector:0.1.0
docker push cdlee/stock-iot-collector:0.1.0
```

Run with Docker:

```bash
docker run --rm \
  -e POLYGON_API_KEY="your_polygon_api_key" \
  -e THINGSBOARD_MQTT_HOST="thingsboard.example.com" \
  -e THINGSBOARD_MQTT_CA_CERT="/etc/stock-iot-collector/certs/ca.crt" \
  -e THINGSBOARD_MQTT_CLIENT_CERT="/etc/stock-iot-collector/certs/client.crt" \
  -e THINGSBOARD_MQTT_CLIENT_KEY="/etc/stock-iot-collector/certs/client.key" \
  -v "$PWD/config/stocks.yaml:/etc/stock-iot-collector/stocks.yaml:ro" \
  -v "/path/to/certs:/etc/stock-iot-collector/certs:ro" \
  cdlee/stock-iot-collector:0.1.0
```

By default, Docker uses `config/stocks.yaml`, which collects all U.S. stocks with `symbol: "*"`.

## Kubernetes Deployment

### 1. Use The Docker Hub Image

The Kubernetes deployment uses the Docker Hub image:

```yaml
image: cdlee/stock-iot-collector:0.1.0
```

If you publish a new image tag, update `k8s/deployment.yaml`:

```yaml
image: cdlee/stock-iot-collector:<tag>
```

### 2. Create Namespace

```bash
kubectl apply -f k8s/namespace.yaml
```

### 3. Create Secret

The collector needs the Polygon API key and the MQTT TLS files.

Set your API key in the shell:

```bash
export POLYGON_API_KEY="your_polygon_api_key"
```

Create or update the Kubernetes secret:

```bash
kubectl create secret generic stock-iot-collector-secret \
  -n stock \
  --from-literal=POLYGON_API_KEY="$POLYGON_API_KEY" \
  --from-file=ca.crt=full-ca.crt \
  --from-file=client.crt=client.crt \
  --from-file=client.key=client.key \
  --dry-run=client -o yaml | kubectl apply -f -
```

Expected files:

```text
full-ca.crt
client.crt
client.key
```

`client.crt` and `client.key` must match the ThingsBoard gateway device credentials.

### 4. Configure The Collector

Edit `k8s/configmap.yaml`.

Set the MQTT host:

```yaml
THINGSBOARD_MQTT_HOST: "mqtt.example.com"
```

The default configuration collects all U.S. stocks:

```yaml
stocks.yaml: |
  stocks:
    - symbol: "*"
```

If ThingsBoard is under pressure, lower the chunk size:

```yaml
PUBLISH_CHUNK_SIZE: "10"
```

A smaller watchlist is optional and can be configured later if you do not want all U.S. stocks.

### 5. Deploy

```bash
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml
```

### 6. Verify

Check the pod:

```bash
kubectl get pods -n stock
```

Follow logs:

```bash
kubectl logs -n stock -l app=stock-iot-collector -f
```

Healthy logs look like:

```text
Loaded ... stock(s), daily mode
MQTT connection accepted: Success
Connected to ThingsBoard MQTT host=...
Published telemetry for ... stock(s)
Sleeping for 3600 second(s)
```

Stop the deployment:

```bash
kubectl scale deployment -n stock stock-iot-collector --replicas=0
```

Start it again:

```bash
kubectl scale deployment -n stock stock-iot-collector --replicas=1
```

## Configuration

Required environment variables:

| Variable | Description |
| --- | --- |
| `POLYGON_API_KEY` | Polygon/Massive API key. |
| `THINGSBOARD_MQTT_HOST` | ThingsBoard MQTT host. |
| `THINGSBOARD_MQTT_CA_CERT` | CA certificate used to verify the MQTT TLS server. |
| `THINGSBOARD_MQTT_CLIENT_CERT` | Client X.509 certificate for the ThingsBoard gateway device. |
| `THINGSBOARD_MQTT_CLIENT_KEY` | Private key matching the client certificate. |

Optional environment variables:

| Variable | Default | Description |
| --- | --- | --- |
| `STOCK_CONFIG_PATH` | `./config/stocks.yaml` locally, otherwise `/etc/stock-iot-collector/stocks.yaml` | Stock config path. |
| `DAILY_MARKET_DAYS_AGO` | `1` | Collect the previous N U.S. market weekdays. |
| `BACKFILL_MARKET_DAYS` | `0` | When greater than `0`, run a one-time backfill for the previous N U.S. market weekdays, then exit. |
| `POLYGON_MAX_RETRIES` | `5` | Number of retries for Polygon/Massive HTTP requests, especially rate-limit responses. |
| `POLYGON_RETRY_BASE_SECONDS` | `60` | Base wait time for Polygon/Massive retry backoff when no `Retry-After` header is provided. |
| `POLL_INTERVAL_SECONDS` | `3600` | How often the collector runs. |
| `PUBLISH_CHUNK_SIZE` | `50` | Number of virtual devices per MQTT gateway telemetry message. Lower this if ThingsBoard is under pressure. |
| `THINGSBOARD_MQTT_PORT` | `8883` | MQTT TLS port. |
| `THINGSBOARD_MQTT_CLIENT_ID` | `stock-collector-01` | MQTT client id. |
| `MQTT_KEEPALIVE_SECONDS` | `60` | MQTT keepalive. |

## Historical Backfill

To backfill the previous 90 U.S. market weekdays, run the collector with:

```bash
export BACKFILL_MARKET_DAYS="90"
python -m app.main
```

Backfill mode runs once and exits. Do not set `BACKFILL_MARKET_DAYS` on the long-running Kubernetes Deployment, otherwise Kubernetes will restart the pod and repeat the backfill. For Kubernetes, run backfill as a temporary one-off pod or Job, then keep the normal Deployment on `BACKFILL_MARKET_DAYS=0`.

For all U.S. stocks, 90 market days can publish more than one million telemetry points. If ThingsBoard is under pressure, reduce `PUBLISH_CHUNK_SIZE` and run the backfill during a quiet period.

Polygon/Massive may return HTTP 429 during large backfills. The collector retries those requests without logging the API key. If your plan has a strict rate limit, keep `POLYGON_RETRY_BASE_SECONDS=60` or increase it.

## Stock Selection

Collect all U.S. stocks:

```yaml
stocks:
  - symbol: "*"
```

Collect a smaller watchlist:

```yaml
stocks:
  - symbol: AAPL
  - symbol: MSFT
  - symbol: NVDA
```

The collector publishes each ticker as a ThingsBoard virtual device named `stock.{SYMBOL}`, for example `stock.AAPL`.

## ThingsBoard Requirements

Create one gateway device:

```text
Device name: stock-collector-01
Is gateway: enabled
Credentials: X.509 certificate
```

The collector publishes to:

```text
v1/gateway/telemetry
```

Payload example:

```json
{
  "stock.AAPL": [
    {
      "ts": 1777320000000,
      "values": {
        "open": 173.2,
        "high": 173.5,
        "low": 173.1,
        "close": 173.4,
        "price": 173.4,
        "volume": 1200345,
        "source": "polygon",
        "bar_timestamp_ms": 1777320000000
      }
    }
  ]
}
```

## Notes

This is not a trading system. It is a delayed telemetry ingestion pipeline for monitoring, dashboards, and alerts.
