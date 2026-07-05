#!/usr/bin/env bash
set -euo pipefail

systemctl --user stop cdw-bkdapp.service
systemctl --user status --no-pager cdw-bkdapp.service || true