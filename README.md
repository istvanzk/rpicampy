# Time-lapse with Rasberry Pi controlled (pi)camera.

![Exp](https://img.shields.io/badge/Dev-Experimental-orange.svg)
[![Lic](https://img.shields.io/badge/License-Apache2.0-green)](http://www.apache.org/licenses/LICENSE-2.0)
![Py](https://img.shields.io/badge/Python-3.12+-green)
![Ver](https://img.shields.io/badge/Version-8.2-blue)

## Implementation and configuration

### Components

#### rpiconfig.yaml:	The configuration file with parameters for most of the functionalities.

  - The parameters are grouped in 6 sections: *Main*, *timerConfig*, *camConfig*, *dirConfig*, *dbxConfig* and *rcConfig*. 
  See comments in the [rpiconfig.yaml](./rpiconfig.yaml) file for all available configuration parameters and their use.

#### rpicam_sch:  The main method. 

- Uses the [Advanced Python Scheduler](http://apscheduler.readthedocs.org/en/latest/) to background schedule the three main interval jobs implemented in rpicam, rpimgdir and rpimgdb. 

- Schedule an additional background timer job to collect/combine the status messages from the rpi scheduled jobs, and to send/receive remote control commands via ThingSpeak TalkBack App. All classes described below have a remote control interface to this timer job.

- When SystemD is used the module notifies the [systemd](https://www.freedesktop.org/software/systemd/python-systemd/) (when available) with: READY=1, STATUS=, WATCHDOG=1 (read env variable WATCHDOG_USEC=), STOPPING=1.

- Use of Picamera2 (2022+):
  - When `RPICAM2` is set in `rpiconfig.yaml` under the Main section, then the [Picamera2 API](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf) is used.

  - When `LIBCAMERA` is set in `rpiconfig.yaml` under the Main section, then [rpicam-still](https://www.raspberrypi.com/documentation/computers/camera_software.html#rpicam-still)  is used from rpicam-apps installed with picamera2.

  - When `RPICAM2` or `LIBCAMERA` is set in `rpiconfig.yaml`, a camera tunning file (--tuning-file) is used, auto-configured by setting the `cam_version` and `cam_type` specified in the `rpiconfig.yaml` under the `camConfig` section.

  - When neither `RPICAM2` or `LIBCAMERA` are set, the `FAKESNAP` can be used to fake an image capture.
  - When neither `RPICAM2`, `LIBCAMERA` or `FAKESNAP` are set, then the webcam `fswebcam` utility is used to capture images.

  - Example testing the installation with [camtest.sh](./scripts/camtest.sh)

- Gracefull exit is implemented for SIGINT, SIGTERM and SIGABRT.

**Run manually**: 

Use 
```
RPI_LGPIO_REVISION=800012 python3 rpicam_sch.py &
```
NOTE: The `RPI_LGPIO_REVISION` environment variable must be set due the use of the user-space GPIO access is via the [rpi.gpio compatibility package](https://rpi-lgpio.readthedocs.io/en/latest/index.html), on Linux kernels which support [/dev/gpiochipX](https://www.thegoodpenguin.co.uk/blog/stop-using-sys-class-gpio-its-deprecated/).

**Auto-start as service**: 

Use the SystemD user service unit `rpicamsch.service.user`.
The `rpicamsch.service.user` systemd user service unit is to be copied to /etc/systemd/user/rpicamsch.service.

While running, all messages are logged to a (rotated) `rpicam.log` file. The log level is configured in `rpilogger.py`.

#### rpicam:	Manage image capture with (pi)camera and save images locally.

Image capture options are selected in `rpiconfig.yaml` under the Main section (see above).

The captured images are stored locally in a sub-folder with the current date 'DDMMY' as name, under the `image_dir` folder, specified in the configuration file under the `dirConfig` section.
The captured image local file names are 'DDMMYY-HHMMSS-CAMID.jpg', where CAMID is the camera identification string `cam_id`, specified in the configuration file under the `camConfig` section.

The module implements a 'dark' time long exposure time or an IR/VL reflector ON/OFF switch. The module implements the infra-red (IR) or visible light (VL) reflector control via GPIO (configured with `use_irl: yes` and `bcm_irlport` parameters in the configuration file under the `camConfig` section).

- The 'dark' time period (start and stop) can be configured manually using the hour/min parameters set in the configuration file under the `timerConfig` section.
- Alternatively, the 'dark' time period can be configured automatically using the [PyEphem](http://rhodesmill.org/pyephem/) 
and the location parameters (latitude and longitude) `lat_lon` set in the configuration file under the `camConfig` section.

PIR sensor support, as external trigger via GPIO for the camera job, is in BETA. (replaces the normal camera job scheduler when configured with `use_pir: yes` and `bcm_pirport` parameters in the configuration file under the `camConfig` section).


<details>
<summary>Further info about the other implemenation modules</summary>

### General functionalities/modules

#### rpimgdir:	Manage the set of locally saved images by rpicam.  

#### rpimgdb:	Manage images in a Dropbox remote directory (API V2).

  - The captured images are uploaded to a sub-folder with the current date 'DDMMYY' as name, under the `image_dir` folder, under the Dropbox App folder.
  - The captured image upload file names are 'DDMMYY-HHMMSS-CAMID.jpg', where CAMID is the camera identification string `cam_id`, specified in the configuration file under the `camConfig` section.
  - The current/last captured image is always uploaded with the name `image_snap`, specified in the configuration file under the `dbConfig` section,
  under the `image_dir` folder, under the Dropbox App folder.
  - All uploaded images file names are stored in in a local `upldlog.json` file when the configured capture sequence ends or at the end of each day.

#### rpibase:	Base class for rpicam, rpimgdir and rpimgdb (see above).

#### rpievents:	Implements the set of events and counters to be used in the rpi classes.

#### rpififo:	Implements the FIFO buffer for the image file names (full path) generated in the rpicam.

### Communication channels
> NOTE: Work ongoing! Not fully operational yet.

There are three types of communication channels available:
- ts-*  = ThingSpeak feed and TalkBack REST feed (as client)
- aio-* = Adafruit IO feed (as client)
- ws-*  = Websocket (as server)

There are three levels of communication possible on each channel: 
- L1: '*-sr' = Periodic status report send/receive, 
- L2: '*-rr' = L1 + config param retrival (request and reply)
- L3: '*-cc' = L2 + command and control (c2)

The currently supported communication options are:
- 'ts-sr'  = ThingSpeak feed status report send
- 'ts-cc'  = ThingSpeak feed receive command/control and send feedback on TalkBack REST feed
- 'aio-sr' = Adafruit IO feed
- 'ws-sr'  = WebSockets

The above communication channels and options are specified in the `rcConfig` section of the `rpiconfig.yaml`, for example like:
```
rc_type: ['ts-sr', 'ws-cc]
token_file: ['ts_tokens.txt', 'ws_tokens.txt']
```
See description below for details on each.

If `rc_type` is empty, all communication channels are disabled, regardless of `token_file` settings.
If there is no token file listed in `token_file` for a specific communication channel, that communication channel is disabled, regardless of `rc_type` settings.
If the `token_file` list is empty, all communication channels are disabled, regardless of `rc_type` settings.

#### thingspk:	A simple REST request abstraction layer and a light client ThingSpeak API and TalkBack API. 

  The implementation of the thingspk module follows the [ThingSpeak API documentation](https://www.mathworks.com/help/thingspeak/)
  and the [TalkBack API documentation](https://www.mathworks.com/help/thingspeak/talkback-app.html). The REST client implementation follows the model of the older [Python Xively API client](https://github.com/xively/xively-python).

  The use of the ThingSpeak API (to send status messages) and ThingSpeak TalkBack API (to receive remote control commands) requires
  in the `rcConfig`section of the `rpiconfig.yaml` the configuration of:
```
  rc_type: ['ts-sr', 'ts-cc']
  token_file: ['ts_tokens.txt']
```

  where `ts_tokens.txt` (only example file name) is a text file which contains 2 lines with the necessary ThingSpeak API client access keys, as follows:

```
  <channel_id>,<write_key>,<read_key>
  <talkback_id>,<talkback_key>
```

#### rpiaio: A lite wrapper for AIO API client to send status messages to an AIO dashboard.

The use of the AIO API (to send status messages) requires in the `rcConfig`section of the `rpiconfig.yaml` the configuration of:

```
  rc_type: ['aio-sr']
  token_file: ['aio_tokens.txt']
```

  where `aio_tokens.txt` (only example file name) is a text file which contains one line with the necessary AIO API client/user id and access key, as follows:
```
  <user_id>,<access_key>
```

#### rpiwsocket: A simple threaded WebSocket server implementation to send status messages and receive remote control commands.

  The use of the WebSocket server to send status messages and/or receive remote control commands requires in the `rcConfig` section of the `rpiconfig.yaml` the configuration of:
```
  rc_type: ['ws-sr', 'ws-cc']
  token_file: ['ws_tokens.txt']
```

where `ws_tokens.txt` (only example file name) is a text file with the access tokens which need to be provided by each client during the initial authorisation handshake, when connecting to this server, as follows:

```
  <recv_status_token>,<send_cmd_token>
```

#### rpiconfig:	Implements the rpicampy configuration (read `rpiconfig.yaml`) and performs system checks.

#### rpilogger:	Implements the custom logging for the rpicampy.

</details>


### Dependencies 

#### Dependencies on other python modules

Installed with `sudo apt install --upgrade python3-<package>` or `python3 -m pip install -U <package>`

- apscheduler: [Advanced Python Scheduler](https://pypi.python.org/pypi/APScheduler)

- yaml: [YAML](https://packages.debian.org/bookworm/python3-yaml)

- pil: [PIL](https://pillow.readthedocs.io/en/latest/)

- piexif: [Piexif](https://piexif.readthedocs.io/en/latest/index.html)

- ephem: [PyEphem](https://packages.debian.org/bookworm/python3-ephem)

- dropbox:  [Python SDK for Dropbox API v2](https://github.com/dropbox/dropbox-sdk-python)

- rpi-lgpio: [rpi.gpio compatibility package](https://rpi-lgpio.readthedocs.io/en/latest/index.html) on Linux kernels which support /dev/gpiochipX

- systemd: [python3-systemd](https://github.com/systemd/python-systemd)

- websockets: [python3-websockets](https://pypi.org/project/websockets/)

- Adafruit_IO: [adafruit-io](https://github.com/adafruit/Adafruit_IO_Python)

#### System dependencies

Installed with `sudo apt install --upgrade <package>`

- libopenjp2-7: [libopenjp2](https://packages.debian.org/stable/libs/libopenjp2-7), required by Pillow

- fontconfig: [fontconfig](https://packages.debian.org/bookworm/fontconfig) provides Dejavu fonts

Run full system update with `sudo apt-get update && sudo apt-get full-upgrade -y`

### Helper scripts
(in [scripts](.scripts) folder)

#### dbauth: Perform Dropbox authentication, token refresh, and saving to local file the OAuth2 tokens.

#### camdet: Detect camera with Picamera2 API.

#### camdev: Development and tests with Picamera2 API.

#### camtest: Shell script to test Picamera2 with rpicam-still

#### rpicamsch.sh: Deprecated init.d script