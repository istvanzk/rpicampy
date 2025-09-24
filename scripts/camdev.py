#!/usr/bin/env python
# -*- coding: utf-8 -*-
""" Development with Picamera2 API """
import sys
import os
import time
import logging

import piexif
from fractions import Fraction
import io
from PIL import Image, ImageDraw, ImageFont, ImageStat

# Set the logging parameters
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

# GPIO module
try:
    import RPi.GPIO as GPIO
except NotImplementedError as e:
    logger.error(f"rpicam::: The RPi.GPIO (rpi-lgpio) module could not be initialized! {e}\n")
    raise ImportError("The RPi.GPIO (rpi-lgpio) module could not be initialized!\nTry running with the RPI_LGPIO_REVISION=800012` environment variable set.")
except ImportError:    
    logger.error("rpicam::: The RPi.GPIO (rpi-lgpio) module could not be loaded!")
    raise ImportError("The RPi.GPIO (rpi-lgpio) module could not be loaded!")

# Picamera2 module
try:
    from picamera2 import Picamera2, Preview
    from libcamera import controls, Transform
except ImportError:    
    logger.error("rpicam::: The picamera2 (v2) module could not be loaded!")
    raise ImportError("The picamera2 (v2) module could not be loaded!\nTry running `sudo apt-get update && sudo apt-get full-upgrade -y`")

# Custom camera tuning modules
LIBCAMERA_JSON = "ov5647_noir.json"

# Camera object and image capture parameters
_tuning = Picamera2.load_tuning_file(f"{LIBCAMERA_JSON:s}")
#camera = Picamera2()
camera = Picamera2(tuning=_tuning)

rotation = 180
resolution = (1024, 768)
jpgqual = 85
camid = "CAM1"
exif_tags_copyr = "Copyright (c) 2025 Istvan Z. Kovacs - All rights reserved"

# Text overlay parameters
TXTfont = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)

# Image file path
image_path = "webcam/camdev_test.jpg"

# The dark setting
useDark = True

# The use of IRL
useIRL = False
# The GPIO BCM port number for the IR light
IRLport = 19

# The use of image overlay text
useTXT = True

def _setCamExp(is_dark: bool, use_irl: bool):
    """ 
    Set camera exposure according to the 'dark' time threshold.
    See Apendix C in Picamera2 API documentation. 
    """
    # print("camera_controls:\n{camera.camera_controls}")
    # {'AnalogueGainMode': (0, 1, 0), 'HdrMode': (0, 4, 0), 'AwbEnable': (False, True, None), 
    # 'ScalerCrop': ((0, 0, 64, 64), (0, 0, 2592, 1944), (0, 0, 2592, 1944)), 
    # 'AeMeteringMode': (0, 3, 0), 'ExposureTime': (130, 3066985, 20000), 'FrameDurationLimits': (63965, 3067365, 33333), 
    # 'SyncMode': (0, 2, 0), 'SyncFrames': (1, 1000000, 100), 
    # 'Saturation': (0.0, 32.0, 1.0), 'StatsOutputEnable': (False, True, False), 'CnnEnableInputTensor': (False, True, False), 
    # 'AwbMode': (0, 7, 0), 'Contrast': (0.0, 32.0, 1.0), 'AeEnable': (False, True, True), 
    # 'Sharpness': (0.0, 16.0, 1.0), 'NoiseReductionMode': (0, 4, 0), 'ColourTemperature': (100, 100000, None), 
    # 'AeFlickerPeriod': (100, 1000000, None), 
    # 'AnalogueGain': (1.0, 63.9375, 1.0), 'ColourGains': (0.0, 32.0, None), 
    # 'AeFlickerMode': (0, 1, 0), 'ExposureTimeMode': (0, 1, 0), 
    # 'AeExposureMode': (0, 3, 0), 'ExposureValue': (-8.0, 8.0, 0.0), 
    # 'Brightness': (-1.0, 1.0, 0.0), 'AeConstraintMode': (0, 3, 0)}

    # Get current exposure time and gain
    # https://github.com/raspberrypi/picamera2/discussions/131
    camera.start()
    time.sleep(2)
    metadata = camera.capture_metadata()
    exposure = metadata["ExposureTime"]
    gain = metadata["AnalogueGain"] * metadata["DigitalGain"]
    camera.stop()
    print(f"Current exposure time: {exposure} usec, gain: {gain:.2f}")  

    if is_dark:

        if use_irl:
            camera.set_controls(
            {
                #"AwbEnable": False, 
                #"AwbMode": controls.AwbModeEnum.Auto, 
                "AeEnable": False, 
                #"AeExposureMode": controls.AeExposureModeEnum.Long,
                #"AeConstraintMode": controls.AeConstraintModeEnum.Shadows,
                "ExposureTime": 400000, #usec
                #"ExposureValue": 1, #Floating point number between -8.0 and 8.0
                #"AnalogueGain": 1.0,
                "Contrast": 4.0, # Floating point number from 0.0 to 32.0
                #"Brightness": 0.2, # Floating point number from -1.0 to 1.0
                #"FrameDurationLimits": (2000000,1000000), #usec
            }
            )

        else:
            #    "AeExposureMode": controls.AeExposureModeEnum.Custom, requires definition in /usr/share/libcamera/ipa/rpi/vc4/ov5647_noir.json
            camera.set_controls(
            {
                #"AwbEnable": False, 
                #"AwbMode": controls.AwbModeEnum.Auto,
                "AeEnable": False, 
                #"AeExposureMode": controls.AeExposureModeEnum.Long,
                "ExposureTime":10000000, #usec
                #"ExposureValue": 0, #Floating point number between -8.0 and 8.0
                #"AnalogueGain": 1.0,
                "Contrast": 3.0, # Floating point number from 0.0 to 32.0
                #"Brightness": 0.2, # Floating point number from -1.0 to 1.0
                #"FrameDurationLimits": (2000000,2000000), #usec
            }
            )        

    else:
        camera.set_controls(
        {
            "AwbEnable": True, 
            "AwbMode": controls.AwbModeEnum.Daylight,
            "AeEnable": True, 
            "AeExposureMode": controls.AeExposureModeEnum.Normal,
            "Contrast": 1.0, # Floating point number from 0.0 to 32.0
            "Brightness": 0.0, # Floating point number from -1.0 to 1.0
        }
        )

def _switchIR(bONOFF):
    '''
    Switch ON/OFF the IR lights
    '''
    if bONOFF:
        GPIO.output(IRLport,GPIO.HIGH)
    else:
        GPIO.output(IRLport,GPIO.LOW)

def main():
    """ Main function """
    
    # Get input args
    if len(sys.argv) > 1:
        useDark = sys.argv[1]=='1'
        if len(sys.argv) > 2:
            useIRL = sys.argv[2]=='1'
    if useDark:
        print("Using 'dark' time camera settings")
    else:
        print("Using 'daylight' time camera settings")
    if useIRL:
        print("Using IR light for image capture")
    else:
        print("No IR light for image capture")


    # Setup the GPIO for IRL control
    if useIRL:
        GPIO.setmode(GPIO.BCM)
        if GPIO.getmode() is not None: # GPIO is set
            GPIO.setup(IRLport, GPIO.OUT, initial=0)
            _switchIR(False)
        else:
            GPIO.cleanup()
            raise RuntimeError("GPIO could not be set!")

    #_preview_config = camera.create_preview_configuration()
    #camera.configure(_preview_config)
    #camera.start_preview(Preview.DRM)

    _still_config = camera.create_still_configuration()
    _still_config['main']['size'] = resolution

    # Set camera image rotation
    # Note: libcamera Transform does not support +/-90 degree rotation, so we apply it later with the PIL image (CCW)
    if rotation in [90, -270]:
        _orientation = 6
    elif rotation in [-90, 270]:
        _orientation = 8
    elif rotation == 180:
        _orientation = 3
        _still_config["transform"] = Transform(hflip=1, vflip=1)
    else:
        _orientation = 1

    camera.configure(_still_config)
    camera.options["quality"] = jpgqual

    # Set custom EXIF/TIFF tags
    # https://exiv2.org/tags.html
    # https://github.com/hMatoba/Piexif/blob/master/piexif/_exif.py
    # 0th IFD for primary image data (saved under TIFF data)
    # Exif IFD for Exif-specific attribute information (saved under EXIF data)
    _custom_exif = {
        '0th': {
                    piexif.ImageIFD.Model: camera.camera_properties["Model"],
                    piexif.ImageIFD.Make: "Raspberry Pi",
                    piexif.ImageIFD.Software: "rpicampy",
                    piexif.ImageIFD.DateTime: time.strftime('%Y:%m:%d %H:%M:%S', time.localtime()),
                    piexif.ImageIFD.Artist: camid,
                    piexif.ImageIFD.ImageDescription: "Time-lapse with Rasberry Pi controlled (pi)camera",
                    piexif.ImageIFD.Copyright: exif_tags_copyr, 
                    piexif.ImageIFD.Orientation: 1,
                    piexif.ImageIFD.XResolution: (resolution[0],1),
                    piexif.ImageIFD.YResolution: (resolution[1],1),
                },
        'Exif': {
                    piexif.ExifIFD.DateTimeOriginal: time.strftime('%Y:%m:%d %H:%M:%S', time.localtime()),
                }
        }

    # Set camera exposure according to the 'dark' mode
    # Setting a new exposure time and gain before restarting the camera means it takes effect immediately.
    _setCamExp(useDark, useIRL)

    # Enable IRL if used
    if useIRL:
        _switchIR(True)

    # Start the camera
    camera.start()
    time.sleep(1)

    # Capture image to memory
    stream = io.BytesIO()
    camera.capture_file(stream, format='jpeg', exif_data=_custom_exif)

    # Disable IRL if used
    if useIRL:
        _switchIR(False)

    if useTXT:

        # Read stream to a PIL image
        #(buffer, ), metadata = camera.capture_buffers(["main"])
        #image = camera.helpers.make_image(buffer, _still_config["main"])
        stream.seek(0)
        image = Image.open(stream)

        # Apply +/-90 degree rotation with PIL (CCW)
        if rotation in [90, -90, 270, -270]:
            image = image.rotate(rotation, expand=True)
        
        # When in 'dark' time
        # Calculate brightness and adjust shutter speed when not using IR light
        # ...

        # Add overlay text to the final image
        draw = ImageDraw.Draw(image,'RGBA')
        draw.rectangle([0,image.size[1]-20,image.size[0],image.size[1]], fill=(150,200,150,100))
        if useDark:
            night_irl_str = 'N'
        else:
            night_irl_str = 'D'
        if useIRL:
            night_irl_str += 'I'
        draw.text((2,image.size[1]-18), f"{camid:s} ({night_irl_str:s}) {time.strftime('%b %d %Y, %H:%M', time.localtime()):s}", fill=(0,0,0,0), font=TXTfont)
        #n_width, n_height = TXTfont.getsize('#XX')
        #draw.text((image.size[0]-n_width-2,image.size[1]-18), '#XX', fill=(0,0,0,0), font=TXTfont)
        del draw

        # Save image to the output file
        #camera.helpers.save(img=image, metadata, file_output=image_path, format='jpeg', exif_data=_custom_exif)
        image.save(image_path, format='jpeg', quality=jpgqual, exif=piexif.dump(_custom_exif))

    else:
        # Copy the BytesIO stream to the output file
        # Note: Any +/-90 degree image rotation is NOT applied
        with open(image_path, "wb") as outfile:
            outfile.write(stream.getbuffer())

    # Close BytesIO stream
    stream.close()

    # Close the camera
    camera.stop()

    # GPIO cleanup
    if useIRL:
        GPIO.cleanup()

if __name__ == "__main__":
    main()