# -*- coding: utf-8 -*-
"""
    Time-lapse with Rasberry Pi controlled camera
    Copyright (C) 2016- Istvan Z. Kovacs

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

Implements the a FIFO buffer for the image file names (full path).
"""

from threading import BoundedSemaphore
from collections import deque

class rpiFIFOClass(deque):
    """
    Implements the a Deque with BoundedSemaphore.
    Used as a FIFO buffer for the image file names (including the full path).
    Stores also the name of the current sub-folder.
    """
    def __init__(self, *args):
        super(rpiFIFOClass,self).__init__(*args)
        self.FIFOSema  = BoundedSemaphore()
        self.crtSubDir = '/'
        self.camID     = ''

    def acquireSemaphore(self):
        self.FIFOSema.acquire()

    def releaseSemaphore(self):
        self.FIFOSema.release()

    def __del__(self):
#       self.FIFOSema.release()
        self.crtSubDir = ''
