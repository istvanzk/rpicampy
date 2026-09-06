#!/usr/bin/env python
# -*- coding: utf-8 -*-
""" Development with Picamera2 API """
import sys
import os
import time
import ephem
from datetime import datetime, timezone
import subprocess
import logging
import yaml

# Set the logging parameters
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

# Configuration file
YAMLCFG_FILE = 'rpiconfig.yaml'

# Hostname
HOST_NAME = subprocess.check_output(["hostname", ""], shell=True).strip().decode('utf-8')

### Detect camera type and info
try:
    from picamera2 import Picamera2, Preview
    from libcamera import controls, Transform
except ImportError:    
    logger.error("updconfig::: The picamera2 (v2) module could not be loaded!")
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

### Load configuration file
if os.path.exists(YAMLCFG_FILE):
    with open(YAMLCFG_FILE, 'r') as stream:
        #timerConfig, camConfig, dirConfig, dbxConfig = yaml.load_all(stream, Loader=yaml.SafeLoader)
        _config = yaml.safe_load(stream)
        timerConfig = _config['timerConfig']
        rcConfig = _config['rcConfig']
        camConfig = _config['camConfig']
        dirConfig = _config['dirConfig']
        dbxConfig = _config['dbConfig']

else:
    logger.error("Configuration file not found!")
    sys.exit()

# Add/copy config keys
# Camera capture config
print("=== Edit camera capture configuration ===")

print(f"# Image directory: {camConfig['image_dir']}")
image_dir = input("> Enter the new image directory or press Enter to keep the current one: ")
if image_dir != '':
    camConfig['image_dir'] = image_dir
    print(f"#> New image directory: {camConfig['image_dir']}")

print(f"# Image ID: {camConfig['image_id']}")
image_id = input("> Enter the new image ID or press Enter to keep the current one: ")    
if image_id != '':
    camConfig['image_id'] = image_id
    print(f"#> New image ID: {camConfig['image_id']}")

# TODO: use in code
print(f"Image resolution: {camConfig['resolution']}")
try_again = True
while try_again:
    resolution = input("> Enter the new image resolution Widh and Height values separated by comma, or press Enter to keep the current values: ")
    if resolution != '':
        if len(resolution.split(',')) == 2:
            res = resolution.split(',')
            # TODO: Check if the resolution is valid. Use camera API for this.
            if True:
                camConfig['resolution'] = [int(res[0]), int(res[1])]
                try_again = False
                print(f"#> Newimage resolution: {camConfig['resolution']}")

            else:
                _try = input("Incorrect input values. Try again? y/n")
                try_again = (_try == 'y')
        else:
            _try = input("Incorrect input format. Try again? y/n")
            try_again = (_try == 'y')
    else:
        try_again = False



# TODO: use in code
print(f"Image JPG quality: {camConfig['jpg_quality']}")
try_again = True
while try_again:
    jpg_quality = input("> Enter the new image JPG quality (50..100) or press Enter to keep the current one: ")
    if jpg_quality != '':
        if int(jpg_quality) >= 50 and int(jpg_quality) <=100:
            camConfig['jpg_quality'] = float(jpg_quality)
            try_again = False
            print(f"#> New image JPG quality: {camConfig['jpg_quality']}")

        else:
            _try = input("Incorrect input value. Try again? y/n")
            try_again = (_try == 'y')
    else:
        try_again = False


print(f"Image rotation: {camConfig['image_rot']}")
try_again = True
while try_again:
    image_rot = input("> Enter the new image rotation (0, 90, 180, or 270) or press Enter to keep the current one: ")
    if image_rot != '':
        _rot = int(image_rot)
        if _rot in [0, 90, 180, 270]:
            camConfig['image_rot'] = _rot
            try_again = False
            print(f"#> New image rotation: {camConfig['image_rot']}")

        else:
            _try = input("Incorrect input value. Try again? y/n")
            try_again = (_try == 'y')
    else:
        try_again = False


# TODO: use in code
print(f"Use image overlay text: {'yes' if {camConfig['use_oltxt']} else 'no'}")
use_txt = input("> Enter y/n or press Enter to keep the current setting: ")
if use_txt != '':
    camConfig['use_oltxt'] = (use_txt == 'y')
    print(f"#> Use image overlay text: {'yes' if {camConfig['use_oltxt']} else 'no'}")

# TODO: use as bool in code
print(f"Use IR/V light: {'yes' if camConfig['use_irl'] else 'no'}")
use_irl = input("> Enter y/n or press Enter to keep the current setting: ")
if use_irl != '':
    camConfig['use_irl'] = (use_irl == 'y')
    print(f"#> Use IR/V light: {'yes' if camConfig['use_irl'] else 'no'}")

if camConfig['use_irl']:
    print(f"BCM port for controlling IR/V light (output): {camConfig['bcm_irlport']}")
    bcm_irlport = input("> Enter the new BCM port for IR/V light or press Enter to keep the current one: ")
    if bcm_irlport != '':
        # TODO: Check valid BCM port
        camConfig['bcm_irlport'] = int(bcm_irlport)

        print(f"#> BCM port for controlling IR/V light (output): {camConfig['bcm_irlport']}")

# TODO: use as bool in code
print(f"Use PIR to trigger the camera capture: {'yes' if camConfig['use_pir'] else 'no'}")
use_pir = input("> Enter y/n or press Enter to keep the current setting: ")
if use_pir != '':
    camConfig['use_pir'] = (use_pir == 'y')
    print(f"#> Use PIR to trigger the camera capture: {'yes' if camConfig['use_pir'] else 'no'}")

if camConfig['use_pir']:
    print(f"BCM port for PIR (input): {camConfig['bcm_pirport']}")
    bcm_pirport = input("> Enter the new BCM port for PIR input or press Enter to keep the current one: ")
    if bcm_irlport != '':
        # TODO: Check valid BCM port
        camConfig['bcm_pirport'] = int(bcm_pirport)

        print(f"#> BCM port for PIR (input): {camConfig['bcm_pirport']}")

print(f"Configure dark period manually: start/stop hours: {camConfig['dark_hours']}, start/stop minutes: {camConfig['dark_hours']}")
try_again = True
while try_again:
    cfg_dark = input("> Enter the new dark hour start and stop values (0..23) separated by comma or press Enter to keep the current values: ")
    if cfg_dark != '':
        if len(cfg_dark.split(',')) == 2:
            _dark_h = cfg_dark.split(',')
            if (
                int(_dark_h[0]) >= 0 
                and int(_dark_h[0]) <= 23
                and int(_dark_h[1]) >= 0 
                and int(_dark_h[1]) <= 23
            ):
                camConfig['dark_hours'] = [int(_dark_h[0]), int(_dark_h[1])] 
                try_again = False
                print(f"#> New dark period set: start/stop hours: {camConfig['dark_hours']}")
            
            else:
                _try = input("Incorrect input values. Try again? y/n")
                try_again = (_try == 'y')
        else:
            _try = input("Incorrect input format. Try again? y/n")
            try_again = (_try == 'y')
    else:
        try_again = False

print(f"Configure dark period manually: start/stop hours: {camConfig['dark_hours']}, start/stop minutes: {camConfig['dark_hours']}")
try_again = True
while try_again:
    cfg_dark = input("> Enter the new dark minutes start and stop values (0..59) separated by comma or press Enter to keep the current values: ")
    if cfg_dark != '':
        if len(cfg_dark.split(',')) == 2:
            _dark_m = cfg_dark.split(',')
            if (
                int(_dark_m[0]) >= 0 
                and int(_dark_m[0]) <= 59
                and int(_dark_m[1]) >= 0 
                and int(_dark_m[1]) <= 59
            ):
                camConfig['dark_mins'] = [int(_dark_m[0]), int(_dark_m[1])] 
                try_again = False
                print(f"#> New dark period set: start/stop minutes: {camConfig['dark_mins']}")
            
            else:
                _try = input("Incorrect input values. Try again? y/n")
                try_again = (_try == 'y')
        else:
            _try = input("Incorrect input format. Try again? y/n")
            try_again = (_try == 'y')
    else:
        try_again = False

print(f"Current camera location used to determine local sun setting and rising times: {camConfig['lat_lon'][0]}N, {camConfig['lat_lon'][1]}E")
try_again = True
while try_again:
    geo_loc = input("> Enter the new Geodetic latitude (+N) and longitude (+E) values separated by comma or press Enter to keep the current values: ")
    if geo_loc != '':
        if len(geo_loc.split(',')) == 2:
            _loc = geo_loc.split(',')
            _sun = ephem.Sun()
            _obs = ephem.Observer()
            _obs.date = datetime.now()
            _obs.lat = _loc[0]
            _obs.lon = _loc[1]
            print(f"Current local time: {_obs.date}. Next sunrise at location: {_obs.next_setting(_sun)}. Next sunset at location: {_obs.next_rising(_sun)}")
        
        #camConfig['lat_lon'] = ['57.0774992', '9.9117876']

    else:
        try_again = False

    camConfig['interval_sec'] = [10]

# Timer config

    timerConfig['start_year'] = 2025
    timerConfig['stop_year']  = 2025
    timerConfig['start_month'] = 1
    timerConfig['stop_month'] = 12
    timerConfig['start_day'] = 1
    timerConfig['stop_day'] = 31
    timerConfig['start_hour'] = [0]
    timerConfig['start_min'] = [1]
    timerConfig['stop_hour'] = [23] 
    timerConfig['stop_min'] = [55] 

# TODO: Run script to generate/update the pkl file
# Dropbox config
    dbxConfig['token_file'] = './tokens.pkl'


# Display config info
print("These are the updated settings to be saved to the configuration rpiconfig.yaml file:")

# TODO: Display info


save_updates = "x"
while save_updates not in ['y', 'n']:
    save_updates = input("> Save updates? (y/n)")
if save_updates == 'y':
    with open(YAMLCFG_FILE, 'w') as stream:
        yaml.dump_all([timerConfig, camConfig, dirConfig, dbxConfig], stream, default_flow_style=False)


