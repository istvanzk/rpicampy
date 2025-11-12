#!/bin/bash
echo "==================== Status for rpicamsch ====================="
echo "-------------------- journalctl --------------------"
journalctl --user -eu rpicamsch.service
echo "-------------------- systemctl ---------------------"
systemctl --user --no-pager status rpicamsch.service
echo "==============================================================="
