#!/bin/bash
echo "==================== Status for rpicamsch ====================="
echo "-------------------- journalctl --------------------"
sudo journalctl -b -t rpicamsch
echo "-------------------- systemctl ---------------------"
systemctl --user --no-pager status rpicamsch
echo "==============================================================="
