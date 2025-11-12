#!/bin/bash
systemctl --user stop rpicamsch.service
systemctl --user --no-pager status rpicamsch.service
