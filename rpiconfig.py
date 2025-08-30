# -*- coding: utf-8 -*-
"""
    Time-lapse with Rasberry Pi controlled camera
    Copyright (C) 2017 Istvan Z. Kovacs

    This program is free software; you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation; either version 2 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License along
    with this program; if not, write to the Free Software Foundation, Inc.,
    51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

Implements the rpicampy configuration
"""
import os
import time
import sys
import socket
import subprocess
import signal

from rpilogger import rpiLogger

__all__ = ('HOST_NAME', 'timerConfig', 'camConfig', 'dirConfig', 'dbxConfig',
            'RPIJOBNAMES', 'INTERNETUSE', 'TSPKFEEDUSE', 'RESTfeed', 'TSPKTBUSE', 'RESTTalkB',
            'TSPKFIELDNAMES', 'DROPBOXUSE', 'LOCUSBUSE', 'SYSTEMDUSE', 'WATCHDOG_USEC',
            'rpigexit');

### Custom configuration START

# Configuration file
YAMLCFG_FILE = 'rpiconfig.yaml'

# RPi Job names
RPIJOBNAMES = {'timer':'TIMERJob', 'cam':'CAMJob', 'dir':'DIRJob', 'dbx':'DBXJob'}

# Internet connection
INTERNETUSE = True

# Dropbox storage
DROPBOXUSE  = True

# ThingSpeak API and TalkBack APP
TSPKFEEDUSE = False
TSPKTBUSE   = False

# Local USB storage
LOCUSBUSE   = False

# SystemD use
SYSTEMDUSE  = True

### Custom configuration END




### Python version
PY39 = (sys.version_info[0] == 3) and (sys.version_info[1] >= 9)
if not PY39:
    rpiLogger.error("This program requires minimum Python 3.9!")
    os._exit(1)

### Hostname
HOST_NAME = subprocess.check_output(["hostname", ""], shell=True).strip().decode('utf-8')

### Gracefull exit handler
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


### Read the configuration parameters
try:
    import yaml

    with open(YAMLCFG_FILE, 'r') as stream:
        timerConfigYaml, camConfig, dirConfig, dbxConfig, _ = list(yaml.load_all(stream, Loader=yaml.SafeLoader))

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

    # Extract dark time values from timerConfigYaml
    if timerConfigYaml['start_dark_time'] < 0:
        camConfig['start_dark_hour'] = -1
        camConfig['start_dark_min']  = -1
    elif timerConfigYaml['start_dark_time'] > (len(timerConfigYaml['start_times']) - 1):
        rpiLogger.error("Configuration file error: start_dark_time index out of range!")
        os._exit(1)

    _time = timerConfigYaml['start_times'][timerConfigYaml['start_dark_time']]
    _hms = _time.split(':')
    camConfig['start_dark_hour'] = int(_hms[0])
    camConfig['start_dark_min']  = int(_hms[1])

    if timerConfigYaml['stop_dark_time'] < 0:
        camConfig['stop_dark_hour'] = -1
        camConfig['stop_dark_min']  = -1
    elif timerConfigYaml['stop_dark_time'] > (len(timerConfigYaml['stop_times']) - 1):
        rpiLogger.error("Configuration file error: stop_dark_time index out of range!")
        os._exit(1)

    _time = timerConfigYaml['stop_times'][timerConfigYaml['stop_dark_time']]
    _hms = _time.split(':')
    camConfig['stop_dark_hour'] = int(_hms[0])
    camConfig['stop_dark_min']  = int(_hms[1])

    # Add/copy other config keys
    if len(timerConfigYaml['interval_sec']) != len(timerConfigYaml['start_times']):
        rpiLogger.error("Configuration file error: number of timerConfig['interval_sec'] entries and number of time periods entries do not match!")
        os._exit(1)

    timerConfig['interval_sec'] = timerConfigYaml['interval_sec']
    camConfig['interval_sec']   = timerConfigYaml['interval_sec']

    if len(dirConfig['interval_sec']) > len(timerConfigYaml['start_times']):
        rpiLogger.warning("Configuration file error: number of dirConfig['interval_sec'] entries is larger than number of time periods defined! Using first %d entries." % len(timerConfigYaml['start_times']))
        dirConfig['interval_sec'] = dirConfig['interval_sec'][:len(timerConfigYaml['start_times'])]

    if len(dbxConfig['interval_sec']) > len(timerConfigYaml['start_times']):
        rpiLogger.warning("Configuration file error: number of dbxConfig['interval_sec'] entries is larger than number of time periods defined! Using first %d entries." % len(timerConfigYaml['start_times']))
        dbxConfig['interval_sec'] = dbxConfig['interval_sec'][:len(timerConfigYaml['start_times'])]

    camConfig['list_size'] = dirConfig['list_size']
    dbxConfig['image_dir'] = camConfig['image_dir']
    dirConfig['image_dir'] = camConfig['image_dir']

    # Convert geolocation string to decimal value
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

    camConfig['lat_lon'][0] = _geo2dec(camConfig['lat_lon'][0])
    camConfig['lat_lon'][1] = _geo2dec(camConfig['lat_lon'][1])

    # Add timer operation control flags
    timerConfig['enabled'] = True
    timerConfig['cmd_run'] = False
    timerConfig['stateval']= 0
    timerConfig['status']  = ''

    del timerConfigYaml, _time, _ymd, _hms, _tper
    rpiLogger.info("Configuration file read.")

except yaml.YAMLError as e:
    rpiLogger.error("Error in configuration file:" % e)
    os._exit(1)

except ImportError as e:
    rpiLogger.error("YAML module could not be loaded!")
    os._exit(1)

# Display config info
rpiLogger.debug("timerConfig: %s" % timerConfig)
rpiLogger.debug("camConfig: %s" % camConfig)
rpiLogger.debug("dirConfig: %s" % dirConfig)
rpiLogger.debug("dbxConfig: %s" % dbxConfig)


### Dropbox API use
if DROPBOXUSE :
    if not INTERNETUSE or \
        dbxConfig['token_file'] is None or \
        dbxConfig['token_file'] == '':
        DROPBOXUSE = False
else:
    rpiLogger.info("Dropbox not used.")


### ThingSpeak API and TalkBack APP use
TSPKFIELDNAMES = None
RESTfeed       = None
RESTTalkB      = None
if TSPKFEEDUSE or TSPKTBUSE:
    if not INTERNETUSE or \
        timerConfig['token_file'] is None or \
        timerConfig['token_file'] == '':
        TSPKFEEDUSE = False
        TSPKTBUSE   = False

    else:
        import thingspk

        if TSPKFEEDUSE:
            RESTfeed = thingspk.ThingSpeakAPIClient(timerConfig['token_file'])

            if RESTfeed is not None:
                TSPKFIELDNAMES = {}
                for indx, item in enumerate(RPIJOBNAMES, start=1):
                    TSPKFIELDNAMES[item] = 'field%d' % indx

                for tsf in TSPKFIELDNAMES.values():
                    RESTfeed.setfield(tsf, 0)

                RESTfeed.setfield('status', '---')
                rpiLogger.info("ThingSpeak Channel ID %d initialized. Fields: %s" % (RESTfeed.channel_id, TSPKFIELDNAMES))

            else:
                TSPKFEEDUSE = False
                rpiLogger.warning("ThingSpeak API could not initialized.")

        else:
            rpiLogger.info("ThingSpeak API not used.")

        if TSPKTBUSE:
            RESTTalkB = thingspk.ThingSpeakTBClient(timerConfig['token_file'])
            if RESTTalkB is not None:
                rpiLogger.info("ThingSpeak TalkBack ID %d initialized." % RESTTalkB.talkback_id)

            else:
                rpiLogger.warning("ThingSpeak TalkBack could not be initialized.")

        else:
            rpiLogger.info("ThingSpeak TalkBack APP not used.")

else:
    rpiLogger.info("ThingSpeak not used.")

### Local USB storage
#if LOCUSBUSE:
#   ...
#   rpiLogger.info("USB storage used.")
#else:
#   rpiLogger.info("USB storage not used.")

### Gracefull killer/exit
rpigexit = GracefulKiller()

### Initialization info message
rpiLogger.info("\n\n=== Initialized on %s (INTERNETUSE:%s, DROPBOXUSE:%s, TSPKFEEDUSE:%s, TSPKTBUSE:%s, SYSTEMDUSE:%s) ===\n" % (HOST_NAME, INTERNETUSE, DROPBOXUSE, TSPKFEEDUSE, TSPKTBUSE, SYSTEMDUSE))

