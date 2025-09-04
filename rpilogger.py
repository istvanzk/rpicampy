# -*- coding: utf-8 -*-
"""
    Time-lapse with Rasberry Pi controlled camera
    Copyright (C) 2017- Istvan Z. Kovacs

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

Implements the custom logging for the rpicampy

Inspired by:
    Nicolargo <nicolas@nicolargo.com>
        https://github.com/nicolargo/glances/blob/master/glances/logger.py
and filter setting from:
    http://stackoverflow.com/questions/21455515/install-filter-on-logging-level-in-python-using-dictconfig
"""

import logging
import logging.config

### Logging parameters
LOGLEVEL = logging.INFO
LOGFILEBYTES = 3*102400
LOG_FILENAME = 'rpicam.log'

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
        'level': 'INFO',
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
            'backupCount': 5,
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
