#!/bin/sh
rpicam-still --tuning-file /usr/share/libcamera/ipa/rpi/vc4/ov5647_noir.json -n --immediate --awb 'auto' --gain 3.0 --exposure 'normal' --contrast 5.0 --brightness 0.4 --saturation 1.0 --ev 0 --metering 'average' --width 1024 --height 768 -q 85 --rotation 0  -o $1
