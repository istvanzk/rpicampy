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

Implements the rpiImageDir class to manage the set of saved images by rpiCam
"""
import os
import sys
import glob
import subprocess
from threading import Event
from typing import Any, Dict, List, Tuple

### The rpicampy modules
import rpififo
from rpilogger import rpiLogger
from rpibase import rpiBaseClass, rpiBaseClassError
from rpibase import ERRCRIT, ERRLEV2, ERRLEV1, ERRLEV0, ERRNONE

class rpiImageDirClass(rpiBaseClass):
    """
    Implements the rpiImageDir class to manage the set of saved images by rpiCam
    """

    def __init__(self, name, rpi_apscheduler, rpi_events, rpi_config, cam_rpififo, upld_rpififo):

        ### Init base class
        super().__init__(name, rpi_apscheduler, rpi_events, rpi_config)

        ### Get the Dbx error event
        self._eventDbErr: List[Event] = rpi_events.eventErrList["DBXJob"]

        ### Get FIFO buffer for images from the camera (deque)
        self._imageFIFO: rpififo.rpiFIFOClass = cam_rpififo

        ### Get FIFO buffer for the uploaded images (deque)
        self._imageUpldFIFO: rpififo.rpiFIFOClass = upld_rpififo

        ### As last step, run automatically the initClass()
        self.initClass()

    def __repr__(self):
        return "<%s (name=%s, rpi_apscheduler=%s, rpi_events=dict(), rpi_config=%s, dbuff_rpififo=%s)>" % (self.__class__.__name__, self.name, self._sched, self._config, self._imageFIFO)

    def __str__(self):
        msg = super().__str__()
        return "%s::: config: %s, locdir: %s, image_names: %s, len(imagelist_ref): %d\n%s" % \
                (self.name, self._config, self._locdir, self._image_names, len(self._imagelist_ref), msg)

    def __del__(self):
        ### Clean base class
        super().__del__()


    #
    # Main interface methods
    #

    def jobRun(self):


        ### List all jpg files in the current local sub-folder
        self._locdir = os.path.join(self._config['image_dir'], self._imageFIFO.crtSubDir)
        self._image_names = os.path.join(self._locdir, self._imageFIFO.crtSubDir + '-*' + self._imageFIFO.camID + '.jpg')
        self.imagelist = sorted(glob.glob(self._image_names))
        if len(self.imagelist) > 0:
            rpiLogger.debug("rpimgdir::: jobRun(): imagelist: %s .. %s", self.imagelist[0], self.imagelist[-1])
        else:
            rpiLogger.debug("rpimgdir::: jobRun(): imagelist: empty. No %s found!", self._image_names)

        ### Run directory/file management only if no errors were detected when
        ### updating to remote directory
        if not self._eventDbErr.is_set():
            # Process the new list only if it is changed and has at least max length
            if ( not (self._imagelist_ref == self.imagelist) ) and \
                len(self.imagelist) > self._config['list_size']:

                # Remove all the local images, which are
                # not in the camera buffer and are in the uploaded images buffer
                try:
                    self._imageFIFO.acquireSemaphore()
                    self._imageUpldFIFO.acquireSemaphore()

                    for img in self.imagelist:
                        if not img in self._imageFIFO and \
                            img in self._imageUpldFIFO:
                            rpiLogger.info("rpimgdir::: jobRun(): Remove image: %s", img)
                            self._rmimg = subprocess.Popen("rm " + img, stderr=subprocess.PIPE, stdout=subprocess.PIPE, shell=True)
                            self._diroutput, self._direrrors = self._rmimg.communicate()


                except OSError as e:
                    rpiLogger.warning("rpimgdir::: jobRun(): File %s could not be deleted!\n%s", img, str(e))
                    raise rpiBaseClassError(f"rpimgdir::: jobRun(): File {img} could not be deleted!\n{e}", ERRLEV2)

                except Exception as e:
                    rpiLogger.error("rpimgdir::: jobRun(): Unhandled Exception!\n%s\n", str(e))
                    raise rpiBaseClassError(f"rpimgdir::: jobRun(): Unhandled Exception!", ERRCRIT)

                finally:
                    self._imageFIFO.releaseSemaphore()
                    self._imageUpldFIFO.releaseSemaphore()

            #raise rpiBaseClassError("%s::: jobRun(): Test crash!" % self.name, 4)

            # Update status
            self.statusUpdate = (self.name, len(self.imagelist))

            # Update image list in the current local sub-folder
            self._imagelist_ref = sorted(glob.glob(self._image_names))
            if len(self._imagelist_ref) > 0:
                rpiLogger.debug("rpimgdir::: jobRun(): imagelist_ref: %s .. %s", self._imagelist_ref[0], self.imagelist[-1])
            else:
                rpiLogger.debug("rpimgdir::: jobRun(): imagelist_ref: empty. No %s found!", self._image_names)


        else:
            rpiLogger.info("rpimgdir::: jobRun(): eventDbErr is set!")



    def initClass(self):
        """"
        (re)Initialize the class
        """

        ### Init reference img file list
        self._locdir = os.path.join(self._config['image_dir'], self._imageFIFO.crtSubDir)
        self._image_names = os.path.join(self._locdir, self._imageFIFO.crtSubDir + '-*' + self._imageFIFO.camID + '.jpg')
        self._imagelist_ref = sorted(glob.glob(self._image_names))
        rpiLogger.info("rpimgdir::: initClass(): Initialized image list in local dir %s with %d images.", self._locdir, len(self._imagelist_ref))


#   def endDayOAM(self):
#       """
#       End-of-Day 0AM
#       """

#   def endOAM(self):
#       """
#       End OAM procedure.
#       """
