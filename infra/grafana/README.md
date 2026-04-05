# Grafana

Provisioned assets:

- `provisioning/datasources/prometheus.yml`: default Prometheus datasource at `http://prometheus:9090`
- `provisioning/dashboards/dashboards.yml`: dashboard provider for the `Cozmo` folder
- `dashboards/cozmo-platform-overview.json`: overview dashboard for active calls, setup latency, pipeline RTT, worker saturation, and room quality

With `docker compose` up, Grafana loads the dashboard automatically on startup.
