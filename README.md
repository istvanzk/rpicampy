# Time-lapse with Rasberry Pi controlled (pi)camera.

![Exp](https://img.shields.io/badge/Dev-Experimental-orange.svg)
[![Lic](https://img.shields.io/badge/License-Apache2.0-green)](http://www.apache.org/licenses/LICENSE-2.0)
![Py](https://img.shields.io/badge/Python-3.9+-green)
![Ver](https://img.shields.io/badge/Version-6.0-blue)

## Implementation (rpicampy)

### Components

#### rpicam_sch:	The main method. 

- Uses the [Advanced Python Scheduler](http://apscheduler.readthedocs.org/en/latest/) to background schedule the three main interval jobs implemented in rpicam, rpimgdir and rpimgdb. 

- Schedule an additional background timer job to collect/combine the status messages from the rpi scheduled jobs, and to send/receive remote control commands via ThingSpeak TalkBack App. All classes described below have a remote control interface to this timer job.

- The module notifies the [systemd](https://www.freedesktop.org/software/systemd/python-systemd/) (when available) with: READY=1, STATUS=, WATCHDOG=1 (read env variable WATCHDOG_USEC=), STOPPING=1.

- Use of Picamera2 (2022+)
  - When `LIBCAMERA` is set in the `rpicam.py` module, then rpicam-still is used from rpicam-apps installed with picamera2.
[rpicam-still](https://www.raspberrypi.com/documentation/computers/camera_software.html#rpicam-still) uses a tunning file (--tuning-file), which must be configured by setting the `LIBCAMERA_JSON` in the `rpicam.py` module.

  - When `RPICAM2` is set in the `rpicam.py` module, then the [Picamera2 API](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf) is used.

  - Example testing the installation with 'camtest.sh`

- Gracefull exit is implemented for SIGINT, SIGTERM and SIGABRT.

#### rpiconfig.yaml:	The configuration file with parameters for the functionalities described below.

#### rpicam:	Manage (pi)camera and save images locally.

- Raspberry PI camera using rpicam-still (from rpicam-apps), or

- Raspberry PI camera using the Picamera2 API python module (new libcamera stack), or

- USB web camera using fswebcam utility. 

- Implement infra-red (IR) or visible light (VL) reflector control via GPIO (configured with `use_irl` and `bcm_irlport` parameters)

- Implement PIR sensor as external trigger for the camera job, which replaces the job scheduler (configured with `use_pir` and `bcm_pirport` parameters)

The image file names are:  '%d%m%y-%H%M%S-CAMID.jpg', where CAMID is the image/camera identification string `image_id` specified in the configuration file.
The images are saved locally in a sub-folder under the root `image_dir` folder specified in the cofiguration file. The sub-folder name is the current date `%d%m%y`.
When using picamera module, the images are automatically rotated with the `image_rot` angle (degrees) specified in the configuration file. 

The rpicam module implements a 'dark' time long exposure time or an IR/VL reflector ON/OFF switch. 
The 'dark' time period (start and stop) can be configured manually using the hour/min parameters set in the configuration file.
Alternatively, the 'dark' time period can be configured automatically using the [PyEphem](http://rhodesmill.org/pyephem/) 
and the location parameters (latitude and longitude) set in the configuration file.
During the 'dark' time period the IR light is controlled via the GPIO BCM port number `bcm_irport` when `use_ir=1` set in the configuration file.

Note: GPIO access is via the [rpi.gpio compatibility package](https://rpi-lgpio.readthedocs.io/en/latest/index.html) on Linux kernels which support [/dev/gpiochipX](https://www.thegoodpenguin.co.uk/blog/stop-using-sys-class-gpio-its-deprecated/).

#### rpimgdir:	Manage the set of locally saved images by rpicam.  

#### rpimgdb:	Manage images in a Dropbox remote directory (API V2).

The images are saved remotely in a sub-folder under the root `image_dir` folder specified in the cofiguration file. The sub-folder name is the current date `%d%m%y`.

#### rpibase:	Base class for rpicam, rpimgdir and rpimgdb (see above).

#### rpievents:	Implements the set of events and counters to be used in the rpi classes.

#### rpififo:	Implements the FIFO buffer for the image file names (full path) generated in the rpicam.

#### thingspk:	A simple REST request abstraction layer and a light ThingSpeak API and TalkBack App SDK. 

The implementation of the thingspk module follows the [ThingSpeak API documentation](https://www.mathworks.com/help/thingspeak/)
and the [TalkBack API documentation](https://www.mathworks.com/help/thingspeak/talkback-app.html)
The REST client implementation follows the model of the older [Python Xively API client](https://github.com/xively/xively-python).

#### rpiconfig:	Implements the rpicampy configuration (read `rpiconfig.yaml`) and performs system checks.

#### rpilogger:	Implements the custom logging for the rpicampy.

### Auto-start as service

#### rpicamsch.service.user: systemd user service unit, to be copied to /etc/systemd/user/rpicamsch.service


### Dependencies 

#### Dependencies on other python modules

Installed with `sudo apt install --upgrade python3-<package>`

- apscheduler: [Advanced Python Scheduler](https://pypi.python.org/pypi/APScheduler)

- yaml: [YAML](https://packages.debian.org/bookworm/python3-yaml)

- pil: [PIL](https://pillow.readthedocs.io/en/latest/)

- piexif: [Piexif](https://piexif.readthedocs.io/en/latest/index.html)

- ephem: [PyEphem](https://packages.debian.org/bookworm/python3-ephem)

- dropbox:  [Python SDK for Dropbox API v2](https://github.com/dropbox/dropbox-sdk-python)

- rpi-lgpio: [rpi.gpio compatibility package](https://rpi-lgpio.readthedocs.io/en/latest/index.html) on Linux kernels which support /dev/gpiochipX

- systemd: [python3-systemd](https://github.com/systemd/python-systemd)

#### System dependencies

Installed with `sudo apt install --upgrade <package>`

- libopenjp2-7: [libopenjp2](https://packages.debian.org/stable/libs/libopenjp2-7), required by Pillow

- fontconfig: [fontconfig](https://packages.debian.org/bookworm/fontconfig) provides Dejavu fonts

Run full system update with `sudo apt-get update && sudo apt-get full-upgrade -y`