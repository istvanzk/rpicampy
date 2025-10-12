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

Implements the custom logging for all the rpicampy modules.

Inspired by:
    Nicolargo <nicolas@nicolargo.com>
        https://github.com/nicolargo/glances/blob/master/glances/logger.py
and filter setting from:
    http://stackoverflow.com/questions/21455515/install-filter-on-logging-level-in-python-using-dictconfig
"""
import logging
import logging.config

### The rpicampy modules
from rpiconfig import LOGLEVELSTR, LOGFILEBYTES, BACKUPCOUNT, LOG_FILENAME

### Logging parameters
LOGLEVEL = logging.INFO
if LOGLEVELSTR.upper() == 'DEBUG':
    LOGLEVEL = logging.DEBUG
elif LOGLEVELSTR.upper() == 'WARNING':
    LOGLEVEL = logging.WARNING
elif LOGLEVELSTR.upper() == 'ERROR':
    LOGLEVEL = logging.ERROR
elif LOGLEVELSTR.upper() == 'CRITICAL':
    LOGLEVEL = logging.CRITICAL

### Define the logging filter
# Filter out all messages which are not from the main Jobs
class NoRunningFilter(logging.Filter):

    def __init__(self, filter_str=None):
        logging.Filter.__init__(self, filter_str)
        self.filterstr = filter_str

    def filter(self, rec):
        if self.filterstr is None:
            allow = True
        else:
            allow = self.filterstr not in rec.getMessage()

        return allow

### Define the logging configuration
RPILOGGING = {
    'version': 1,
    'disable_existing_loggers': 'False',
    'root': {
        'level': LOGLEVEL,
        'handlers': ['file', 'console']
    },
    'formatters': {
        'full': {
            'format': '%(asctime)s [%(levelname)s] (%(threadName)-10s) %(message)s'
        },
        'short': {
            'format': '%(asctime)s %(message)s'
        }
    },
    'handlers': {
        'file': {
            'level': LOGLEVEL,
            'class': 'logging.handlers.RotatingFileHandler',
            'mode': 'w',
            'maxBytes': LOGFILEBYTES,
            'backupCount': BACKUPCOUNT,
            'formatter': 'full',
            'filename': LOG_FILENAME,
            'filters': ['NotMainJob']
        },
        'console': {
            'level': 'CRITICAL',
            'class': 'logging.StreamHandler',
            'formatter': 'short',
        }
    },
    'filters':{
        'NotMainJob': {
            '()': NoRunningFilter,
            'filter_str': 'Job_Cmd'
        }
    },
    'loggers': {
        'info': {
            'handlers': ['file'],
            'level': 'INFO'
        },
        'debug': {
            'handlers': ['file', 'console'],
            'level': 'DEBUG'
        },
        'warning': {
            'handlers': ['file', 'console'],
            'level': 'WARNING'
        },
        'error': {
            'handlers': ['file', 'console'],
            'level': 'ERROR'
        }
    }
}

### Build the rpilogger
def rpi_logger():
    """Build and return the logger.
    :return: logger -- Logger instance
    """
    _logger = logging.getLogger()

    # Use the RPILOGGING logger configuration
    logging.config.dictConfig(RPILOGGING)

    return _logger


rpiLogger = rpi_logger()
