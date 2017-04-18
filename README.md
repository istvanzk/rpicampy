# rpicampy
## Time-lapse with Rasberry Pi controlled (pi)camera.

### Implementation

##### Version 4.65 for Python 3.4+

#### rpicam_sch:	The main method. 

- Uses the [Advanced Python Scheduler](http://apscheduler.readthedocs.org/en/latest/) to background schedule the three main interval jobs implemented in rpicam, rpimgdir and rpimgdb. 

- Schedule an additional background timer job to collect/combine the status messages from the rpi scheduled jobs, and to send/receive remote control commands via ThingSpeak TalkBack App. All classes described below have a remote control interface to this timer job.

- The module notifies the [systemd](https://www.freedesktop.org/software/systemd/python-systemd/) (when available) with: READY=1, STATUS=, WATCHDOG=1 (read env variable WATCHDOG_USEC=), STOPPING=1.

- Gracefull exit is implemented for SIGINT, SIGTERM and SIGABRT.

#### rpiconfig.yaml:	The configuration file with parameters for the functionalities described below.

#### rpicam:	Manage (pi)camera and save images locally.

- Raspberry PI camera using using the picamera module, or

- Raspberry PI camera using the raspistill utility, or 

- USB web camera using fswebcam utility. 

- Implement infra-red (IR) or visible light (VL) reflector control via GPIO

The image file names are:  '%d%m%y-%H%M%S-CAMID.jpg', where CAMID is the image/camera identification string `image_id` specified in the configuration file.
The images are saved locally in a sub-folder under the root `image_dir` folder specified in the cofiguration file. The sub-folder name is the current date `%d%m%y`.
When using picamera module, the images are automatically rotated with the `image_rot` angle (degrees) specified in the configuration file. 

The rpicam module implements a 'dark' time long exposure time or an IR/VL reflector ON/OFF switch. 
The 'dark' time period (start and stop) can be configured manually using the hour/min parameters set in the configuration file.
Alternatively, the 'dark' time period can be configured automatically using the [PyEphem](http://rhodesmill.org/pyephem/) 
and the location parameters (latitude and longitude) set in the configuration file.
During the 'dark' time period the IR light is controlled via the GPIO BCM port number `bcm_irport` when `use_ir=1` set in the configuration file.

#### rpimgdir:	Manage the set of locally saved images by rpicam.  

#### rpimgdb:	Manage images in a Dropbox remote directory (API V2).

The images are saved remotely in a sub-folder under the root `image_dir` folder specified in the cofiguration file. The sub-folder name is the current date `%d%m%y`.

#### rpibase:	Base class for rpicam, rpimgdir and rpimgdb (see above).

#### rpievents:	Implements the the set of events and counters to be used in the rpi classes.

#### rpififo:	Implements the a FIFO buffer for the image file names (full path) generated in the rpicam.

#### thingspk:	A simple REST request abstraction layer and a light ThingSpeak API and TalkBack App SDK. 

The implementation of the thingspk module follows the [ThingSpeak API documentation](https://www.mathworks.com/help/thingspeak/)
and the [TalkBack API documentation](https://www.mathworks.com/help/thingspeak/talkback-app.html)
The REST client implementation follows the model of the older [Python Xively API client](https://github.com/xively/xively-python).


### Auto-start as service

#### rpicamsch.sh: System V init script (to be copied to /etc/init.d/rpicamsch.sh)

#### rpicamsch.service.user: systemd service unit, run with --user (to be copied to $HOME/.config/systemd/user/rpicamsch.service)


### Dependencies 

#### Dependencies on other python modules

PIP: requirements.txt, to be used with ```sudo pip3 install -r requirements.txt --upgrade```

- [Advanced Python Scheduler](https://pypi.python.org/pypi/APScheduler)

- [PyYAML](https://pypi.python.org/pypi/PyYAML)

- [PIL](https://pypi.python.org/pypi/PIL)

- [PyEphem](https://pypi.python.org/pypi/pyephem/)

- [Python SDK for Dropbox API v2](https://github.com/dropbox/dropbox-sdk-python)

- [RPi.GPIO](https://pypi.python.org/pypi/RPi.GPIO); the module is installed by default in Raspbian/Wheezy; see alternative below

APT-GET:

- [raspberry-gpio-python](https://sourceforge.net/p/raspberry-gpio-python/wiki/install/)

- [python3-systemd](https://github.com/systemd/python-systemd)

