# -*- coding: utf-8 -*-
"""
    Time-lapse with Rasberry Pi controlled camera
    Copyright (C) 2016- Istvan Z. Kovacs

    Licensed under the Apache License, Version 2.0 (the "License");
    you may not use this file except in compliance with the License.
    You may obtain a copy of the License at

        http://www.apache.org/licenses/LICENSE-2.0

    Unless required by applicable law or agreed to in writing, software
    distributed under the License is distributed on an "AS IS" BASIS,
    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
    See the License for the specific language governing permissions and
    limitations under the License.

Implements the rpicampy configuration
"""
import os
import time
import sys
import socket
import subprocess
import signal

from rpilogger import rpiLogger

__all__ = ('HOST_NAME', 'RPICAMPY_VER',
            'timerConfig', 'camConfig', 'dirConfig', 'dbxConfig', 'rcConfig',
            'RPIJOBNAMES', 'INTERNETUSE', 'DROPBOXUSE', 'LOCUSBUSE', 
            'SYSTEMDUSE', 'WATCHDOG_USEC',
            'rpigexit')

# The version string
RPICAMPY_VER = 'RPiCamPy/V8'

# Configuration file
YAMLCFG_FILE = 'rpiconfig.yaml'

# RPi Job names
RPIJOBNAMES = {'timer':'TIMERJob', 'cam':'CAMJob', 'dir':'DIRJob', 'dbx':'DBXJob'}

# SystemD use
# Requires the python-systemd module installed.
# When SYSTEMDUSE is True, the program will send READY=1, STATUS=, WATCHDOG=1 and STOPPING=1 messages to the systemd daemon.
# The WATCHDOG=1 message is sent only when the systemd watchdog is enabled (WATCHDOG_USEC environment variable is set).
# If set to False, the program will not use any systemd features.
SYSTEMDUSE  = True

# Internet connection
INTERNETUSE = True

# Dropbox storage
# Requires internet connection and token_file in the configuration file.
DROPBOXUSE  = True

# Local USB storage
LOCUSBUSE   = False



### Python version
PY39 = (sys.version_info[0] == 3) and (sys.version_info[1] >= 9)
if not PY39:
    rpiLogger.error("This program requires minimum Python 3.9!")
    os._exit(1)

### Hostname
HOST_NAME = socket.gethostname() # subprocess.check_output(["hostname", ""], shell=True).strip().decode('utf-8')

### Gracefull exit handler
# The program will also handle SIGINT, SIGTERM and SIGABRT signals for gracefull exit.
# http://stackoverflow.com/questions/18499497/how-to-process-sigterm-signal-gracefully
class GracefulKiller:
    """ Gracefull exit function """
    kill_now = False
    def __init__(self):
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)
        signal.signal(signal.SIGABRT, self.exit_gracefully)

        rpiLogger.info("Set gracefull exit handling for SIGINT, SIGTERM and SIGABRT.")

    def exit_gracefully(self,signum, frame):
        self.kill_now = True

### SystemD functions
def journal_send(msg_str):
    """ Send a message to the journald """
    if SYSTEMDUSE:
        journal.send(msg_str)

def daemon_notify(msg_str):
    """ Send notification message to the systemd daemon """
    if SYSTEMDUSE:
        daemon.notify(msg_str)

def _geo2dec(geo_str):
    """ Convert geolocation string to decimal format """
    _geo = geo_str.split(':')
    if len(_geo) != 3:
        rpiLogger.error("Configuration file error: wrong geolocation format!")
        os._exit(1)

    _deg = float(_geo[0])
    _min = float(_geo[1])
    _sec = float(_geo[2])

    if _deg < 0:
        return _deg - (_min / 60.0) - (_sec / 3600.0)
    else:
        return _deg + (_min / 60.0) + (_sec / 3600.0)


### When the DNS server google-public-dns-a.google.com is reachable on port 53/tcp,
# then the internet connection is up and running.
# https://github.com/arvydas/blinkstick-python/wiki/Example:-Display-Internet-connectivity-status
if INTERNETUSE:
    try:
        socket.setdefaulttimeout(5)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
        rpiLogger.info("Internet connection available.")

    except Exception as e:
        rpiLogger.info("Internet connection NOT available. Continuing in off-line mode.")
        INTERNETUSE = False
        pass
else:
    rpiLogger.info("Internet connection not used.")


### Use systemd features when available
WATCHDOG_USEC = 0
if SYSTEMDUSE:
    try:
        from systemd import daemon
        from systemd import journal
        SYSTEMD_MOD = True

    except ImportError as e:
        rpiLogger.warning("The python-systemd module was not found. Continuing without systemd features.")
        SYSTEMD_MOD = False
        pass

    SYSTEMDUSE = SYSTEMD_MOD and daemon.booted()
    if SYSTEMDUSE:
        try:
            WATCHDOG_USEC = int(os.environ['WATCHDOG_USEC'])

        except KeyError as e:
            rpiLogger.warning("Environment variable WATCHDOG_USEC is not set (yet?).")
            pass

        rpiLogger.info("SystemD features used: READY=1, STATUS=, WATCHDOG=1 (WATCHDOG_USEC=%d), STOPPING=1." % WATCHDOG_USEC)

    else:
        rpiLogger.warning("The system is not running under SystemD. Continuing without SystemD features.")

else:
    rpiLogger.info("SystemD features not used.")


### Read the configuration parameters from the YAML file
try:
    import yaml

    # The configuration file has 5 sections, separated by ---
    with open(YAMLCFG_FILE, 'r') as stream:
        mainConfigYaml, timerConfigYaml, camConfig, dirConfig, dbxConfig, rcConfig = list(yaml.load_all(stream, Loader=yaml.SafeLoader))

    # Extract main configuration parameters from mainConfigYaml
    if 'INTERNETUSE' in mainConfigYaml:
        INTERNETUSE = bool(mainConfigYaml['INTERNETUSE'])
    if 'LOCUSBUSE' in mainConfigYaml:
        LOCUSBUSE = bool(mainConfigYaml['LOCUSBUSE'])

    # Extract date and time period values from timerConfigYaml
    timerConfig = {}
    _ymd = timerConfigYaml['start_date'].split('-')
    timerConfig['start_year']  = int(_ymd[0])
    timerConfig['start_month'] = int(_ymd[1])
    timerConfig['start_day']   = int(_ymd[2]) 

    _ymd = timerConfigYaml['stop_date'].split('-')
    timerConfig['stop_year']  = int(_ymd[0])
    timerConfig['stop_month'] = int(_ymd[1])
    timerConfig['stop_day']   = int(_ymd[2])

    if len(timerConfigYaml['start_times']) != len(timerConfigYaml['stop_times']):
        rpiLogger.error("Configuration file error: number of start_times and stop_times entries do not match!")
        os._exit(1)

    timerConfig['start_hour'] = [0] * len(timerConfigYaml['start_times'])
    timerConfig['start_min']  = [0] * len(timerConfigYaml['start_times'])
    timerConfig['stop_hour']  = [0] * len(timerConfigYaml['stop_times'])
    timerConfig['stop_min']   = [0] * len(timerConfigYaml['stop_times'])

    for _tper, _time in enumerate(timerConfigYaml['start_times']):
        _hms = _time.split(':')
        timerConfig['start_hour'][_tper]  = int(_hms[0])
        timerConfig['start_min'][_tper]   = int(_hms[1])  

    for _tper, _time in enumerate(timerConfigYaml['stop_times']):
        _hms = _time.split(':')
        timerConfig['stop_hour'][_tper]  = int(_hms[0])
        timerConfig['stop_min'][_tper]   = int(_hms[1])

    # Add main timer operation control prameters
    timerConfig['interval_sec'] = timerConfigYaml['interval_sec']
    timerConfig['enabled'] = True
    timerConfig['cmd_run'] = False
    timerConfig['stateval']= 0
    timerConfig['status']  = ''

    # Extract dark time values from timerConfigYaml
    if timerConfigYaml['start_dark_time'] < 0:
        camConfig['start_dark_hour'] = None
        camConfig['start_dark_min']  = None
    elif timerConfigYaml['start_dark_time'] > (len(timerConfigYaml['start_times']) - 1):
        rpiLogger.error("Configuration file error: start_dark_time index out of range!")
        os._exit(1)

    _time = timerConfigYaml['start_times'][timerConfigYaml['start_dark_time']]
    _hms = _time.split(':')
    camConfig['start_dark_hour'] = int(_hms[0])
    camConfig['start_dark_min']  = int(_hms[1])

    if timerConfigYaml['stop_dark_time'] < 0:
        camConfig['stop_dark_hour'] = None
        camConfig['stop_dark_min']  = None
    elif timerConfigYaml['stop_dark_time'] > (len(timerConfigYaml['stop_times']) - 1):
        rpiLogger.error("Configuration file error: stop_dark_time index out of range!")
        os._exit(1)

    _time = timerConfigYaml['stop_times'][timerConfigYaml['stop_dark_time']]
    _hms = _time.split(':')
    camConfig['stop_dark_hour'] = int(_hms[0])
    camConfig['stop_dark_min']  = int(_hms[1])

    # Scheduling (activation) intervals
    if len(camConfig['interval_sec']) > len(timerConfigYaml['start_times']):
        rpiLogger.warning("Configuration file error: number of camConfig['interval_sec'] entries is larger than number of time periods defined! Using first %d entries." % len(timerConfigYaml['start_times']))
        camConfig['interval_sec'] = camConfig['interval_sec'][:len(timerConfigYaml['start_times'])]

    if len(dirConfig['interval_sec']) > len(timerConfigYaml['start_times']):
        rpiLogger.warning("Configuration file error: number of dirConfig['interval_sec'] entries is larger than number of time periods defined! Using first %d entries." % len(timerConfigYaml['start_times']))
        dirConfig['interval_sec'] = dirConfig['interval_sec'][:len(timerConfigYaml['start_times'])]

    if len(dbxConfig['interval_sec']) > len(timerConfigYaml['start_times']):
        rpiLogger.warning("Configuration file error: number of dbxConfig['interval_sec'] entries is larger than number of time periods defined! Using first %d entries." % len(timerConfigYaml['start_times']))
        dbxConfig['interval_sec'] = dbxConfig['interval_sec'][:len(timerConfigYaml['start_times'])]

    # Duplicate some configurations to camConfig
    camConfig['list_size'] = dirConfig['list_size']
    camConfig['image_dir'] = dirConfig['image_dir']

    # PyEphem uses the '57:04:39.4' format!!!
    #camConfig['lat_lon'][0] = _geo2dec(camConfig['lat_lon'][0])
    #camConfig['lat_lon'][1] = _geo2dec(camConfig['lat_lon'][1])

    del mainConfigYaml, timerConfigYaml, _time, _ymd, _hms, _tper
    rpiLogger.info("Configuration file read.")

except yaml.YAMLError as e:
    rpiLogger.error("Error in configuration file:\n" % e)
    os._exit(1)
except KeyError as e:
    rpiLogger.error("Configuration file error: key %s not found!\n" % e)
    os._exit(1)
except ImportError as e:
    rpiLogger.error("YAML module could not be loaded!\n" % e)
    os._exit(1)


### Check internet connection usage and remote control configurations
DROPBOXUSE  = False
if INTERNETUSE:
    # Check Drobox use
    if 'token_file' not in dbxConfig or dbxConfig['token_file'] == '' or \
        'interval_sec' not in dbxConfig or len(dbxConfig['interval_sec']) == 0:
        rpiLogger.info("Dropbox not used.")
    else:
        DROPBOXUSE = True

    # Check Remote Control use
    if 'rc_type' not in rcConfig or not rcConfig['rc_type']:
        rpiLogger.info("No Remote Control option used.")

    else:
        # Check ThingSpeak API and TalkBack APP use
        if ('ts-status' in rcConfig['rc_type'] \
            or 'ts-cmd' in rcConfig['rc_type'] ) \
            and (
                'token_file' not in rcConfig \
                 or rcConfig['token_file'] == []
            ):
            try:
                rcConfig['rc_type'].remove('ts-status')
                rcConfig['rc_type'].remove('ts-cmd')
            except ValueError as e:
                pass
            rpiLogger.info("No 'token_file' configured. ThingSpeak feed and Talkback cannot be used.")

        # Check Websocket use
        if ('ws-status' in rcConfig['rc_type'] \
            or 'ws-cmd' in rcConfig['rc_type'] ) \
            and (
                'port' not in rcConfig or rcConfig['port'] == 0 \
                or 'token_file' not in rcConfig \
                or rcConfig['token_file'] == []
            ):
            try:
                rcConfig['rc_type'].remove('ws-status')
                rcConfig['rc_type'].remove('ws-cmd')
            except ValueError as e:
                pass
            rpiLogger.info("No 'port' or 'token_file' configured. WebSocket cannot be used.")
            
else:
    rpiLogger.info("Internet connection not used!")

### Local USB storage
#if LOCUSBUSE:
#   ...
#   rpiLogger.info("USB storage used.")
#else:
#   rpiLogger.info("USB storage not used.")


### Display config info
rpiLogger.debug("timerConfig: %s" % timerConfig)
rpiLogger.debug("camConfig: %s" % camConfig)
rpiLogger.debug("dirConfig: %s" % dirConfig)
rpiLogger.debug("dbxConfig: %s" % dbxConfig)
rpiLogger.debug("rcConfig: %s" % rcConfig)


### Gracefull killer/exit
rpigexit = GracefulKiller()

### Initialization info message
rpiLogger.info("\n\n=== Initialized on %s (INTERNETUSE:%s, DROPBOXUSE:%s, SYSTEMDUSE:%s) ===\n" % (HOST_NAME, INTERNETUSE, DROPBOXUSE, SYSTEMDUSE))

