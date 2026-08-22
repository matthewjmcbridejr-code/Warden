#!/bin/bash
set -e
echo "--- APPROVAL ---"
xvfb-run -a node test_approval.js
echo "--- DENY ---"
xvfb-run -a node test_deny.js
echo "--- BUILD ---"
xvfb-run -a node test_build.js
echo "--- RESTART ---"
xvfb-run -a node test_restart.js
