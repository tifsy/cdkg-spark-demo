#!/usr/bin/env bash
# Publish the demo inside your tailnet over HTTPS: https://<spark-hostname>.<tailnet>.ts.net
# `tailscale serve` also adds Tailscale-User-Login headers, which the app records as the reviewer.
set -euo pipefail
PORT=${1:-8080}
sudo tailscale serve --bg "$PORT"
tailscale serve status
echo "Stop with: sudo tailscale serve --https=443 off"
