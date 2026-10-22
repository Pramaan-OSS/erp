#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' 'The upstream bootstrap was removed: it installed outside software and fetched mutable source.' 'Use the local startup instructions in README.md.' >&2
exit 1
