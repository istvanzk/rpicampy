#!/bin/bash
systemctl --user start rpicamsch.service
systemctl --user --no-pager status rpicamsch.service
