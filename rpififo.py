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

Implements the the rpiFIFO class to manage a buffer for the image file names (full path).
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
        try:
            self.FIFOSema.release()
        except ValueError:
            pass
    def __del__(self):
#       self.FIFOSema.release()
        self.crtSubDir = ''
