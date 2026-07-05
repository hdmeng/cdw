#!/usr/bin/env bash
set -euo pipefail

systemctl --user daemon-reload
systemctl --user enable --now cdw-bkdapp.service
systemctl --user status --no-pager cdw-bkdapp.service