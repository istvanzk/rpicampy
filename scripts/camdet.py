#!/usr/bin/env python
# -*- coding: utf-8 -*-
""" Detect camera with Picamera2 API """
import sys
import os
import time
import logging

# Set the logging parameters
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

try:
    from picamera2 import Picamera2
    #from libcamera import controls, Transform
except ImportError:    
    logger.error("detectcam::: The picamera2 (v2) module could not be loaded!")
    raise ImportError("The picamera2 (v2) module could not be loaded!")

# Camera object
c = Picamera2()

# Is this camera handled by Raspberry Pi code or not (e.g. a USB cam)
cam_rpi = c._is_rpi_camera()

# The dict with 'Model' name , 'Location', 'Rotation' and 'Id' string, for all attached cameras, one dict per camera
cam_info = c.global_camera_info()

# Print the collected camera info
if cam_rpi:
    print("A camera handled by Raspberry Pi code was detected")
else:
    print("A USB camera detected")

print("Camera info:")
for i, cam in enumerate(cam_info):
    print(f"Camera #{i} - Model: {cam['Model']}, Id: {cam['Id']}, Location: {cam['Location']}, Rotation: {cam['Rotation']}")
