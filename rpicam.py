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

Implements the rpiCam class, to run and control a:
    - Raspberry PI camera using the raspistill utility or
    - Raspberry PI camera usingthe picamera module, or
    - Web camera using fswebcam utility.
GPIO ON/OFF control of an IR/VL reflector for night imaging.
"""
import os
from errno import EEXIST
import time
from datetime import datetime, timedelta
import subprocess
import ephem
import math
import json
from threading import Event, RLock
from typing import Any, Dict, List, Tuple

### The rpicampy modules
import rpififo
from rpiconfig import RPICAMPY_VER, LIBCAMERA_JSON, IMAGE_COPYRIGHT, FAKESNAP, RPICAM2, LIBCAMERA, CONTROLS_JSON 
from rpilogger import rpiLogger
from rpibase import rpiBaseClass, rpiBaseClassError
from rpibase import ERRCRIT, ERRLEV2, ERRLEV1, ERRLEV0, ERRNONE


### Initialize camera capture 'back-end' used
if not(FAKESNAP or LIBCAMERA or RPICAM2):
    rpiLogger.warning("rpicam::: No camera input selected! Will try to use 'fswebcam -d /dev/video0' to capture")
    raise rpiBaseClassError("rpicam::: No camera input selected! Will try to use fswebcam!", ERRLEV2)

if FAKESNAP:
    # Dummy (no image capture!)
    LIBCAMERA  = False
    RPICAM2    = False
    rpiLogger.warning("rpicam::: The FAKESNAP option is used!")

elif RPICAM2:
    # Picamera2 (V2) API
    try:
        from picamera2 import Picamera2, Preview
        from picamera2.controls import Controls
        from libcamera import controls, Transform
    except ImportError:
        rpiLogger.error("rpicam::: The picamera2 (v2) module could not be loaded!\n")
        RPICAM2 = False

    import piexif
    import io
    from PIL import Image, ImageDraw, ImageFont, ImageStat

### GPIO initialization
if LIBCAMERA or RPICAM2:
    # Requires rpi-lgpio compatibility package for rpi.gpio on kernels which support /dev/gpiochipX
    # See https://rpi-lgpio.readthedocs.io/en/latest/index.html
    try:
        import RPi.GPIO as GPIO
        rpiLogger.info("rpicam::: The RPi.GPIO (rpi-lgpio) module is used. %s", GPIO.RPI_INFO)
    except NotImplementedError as e:
        rpiLogger.warning("rpicam::: If the error below reads 'This module does not understand old-style revision codes'")
        rpiLogger.warning("rpicam::: then see https://rpi-lgpio.readthedocs.io/en/latest/differences.html#pi-revision")
        rpiLogger.error("rpicam::: The RPi.GPIO (rpi-lgpio) module could not be initialized!\n%s\n", str(e))
        raise rpiBaseClassError("rpicam::: The RPi.GPIO (rpi-lgpio) module could not be initialized!", ERRCRIT)
    except ImportError as e:
        rpiLogger.error("rpicam::: The RPi.GPIO (rpi-lgpio) module could not be loaded!\n%s\n", str(e))
        raise rpiBaseClassError("rpicam::: The RPi.GPIO (rpi-lgpio) module could not be loaded!", ERRCRIT)
else:
    rpiLogger.warning("rpicam::: The RPi.GPIO module is not used!")
    raise rpiBaseClassError("rpicam::: The RPi.GPIO module is not used!", ERRLEV2)


class rpiCamClass(rpiBaseClass):
    """
    Implements the rpiCam class, to run and control:
    - Fake capture (touch) when FAKESNAP is True, or
    - Raspberry PI camera using rpicam-still (from rpicam-apps installed with picamera2), or
    - Raspberry PI camera using the Picamera2 API python module, or
    - USB web camera using fswebcam utility. 
    Use GPIO to ON/OFF control an IR/VL reflector for night imaging.
    """

    def __init__(self, name, rpi_apscheduler, rpi_events, rpi_config, dbuff_rpififo=None):

        ### Init base class
        super().__init__(name, rpi_apscheduler, rpi_events, rpi_config)

        ### Get the Dbx error event
        self._eventDbErr: List[Event] = rpi_events.eventErrList["DBXJob"]

        ### The FIFO buffer (deque)
        self.imageFIFO: rpififo.rpiFIFOClass = rpififo.rpiFIFOClass([], self._config['list_size'])

        ### The flag indicating that PIR sensor has detected movement since last picture has been captured
        self.pirDetected: Event = Event()
        self.pirDetected.clear()
        self.pirTimeDelta = timedelta(seconds=0)
        self.lastPirDetected = datetime.now()

        ### Camera capture parameters
        self.config_lock: RLock = RLock()
        self.camexp_cliargs: List = list()
        self.cam_clistr: List     = list()

        ### Init GPIO ports, BCMxx pin
        self.IRLport:int = None
        self.PIRport:int = None

        ### As last step, run automatically the initClass()
        self.initClass()

    def __repr__(self):
        return "<%s (name=%s, rpi_apscheduler=%s, rpi_events=dict(), rpi_config=%s, dbuff_rpififo=%s)>" % (self.__class__.__name__, self.name, self._sched, self._config, self.imageFIFO)

    def __str__(self):
        msg = super().__str__()
        return "%s::: %s, config: %s, FAKESNAP: %s, LIBCAMERA: %s, RPICAM2: %s\nimageFIFO: %s\n%s" % \
            (self.name, self._camid, self._config, FAKESNAP, LIBCAMERA, RPICAM2, self.imageFIFO, msg)

    def __del__(self):
        ### Clean up Camera and GPIO
        self._del_cam_gpio()

        ### Clean base class
        super().__del__()

    def _del_cam_gpio(self):
        try:
            ### Close and delete the picamera object
            if self._camera is not None:
                if RPICAM2:
                    self._camera.stop()
                    self._camera.close()
                del self._camera
                self._camera = None

            ### Clean up GPIO on exit
            if not FAKESNAP and GPIO.getmode() is not None:
                if self._config['use_pir']:
                    GPIO.remove_event_detect(self.PIRport)

                if self._config['use_irl']:
                    self._switchIR(False)

                time.sleep(5)
                GPIO.cleanup()

        except:
            pass

    #
    # Main interface methods
    #        

    def jobRun(self):

        ### Check flag indicating that PIR sensor has detected movement since last picture has been captured
        if self._config['use_pir']:
            if self.pirDetected.is_set():
                self.pirDetected.clear()
            else:
                return

        ### Create the daily output sub-folder
        ### Set the full image file path
        #self._config['image_subdir'] = time.strftime('%d%m%y', time.localtime())
        self.imageFIFO.crtSubDir = time.strftime('%d%m%y', time.localtime())
        self._locdir = os.path.join(self._config['image_dir'], self.imageFIFO.crtSubDir)
        try:
            os.mkdir(self._locdir)
            rpiLogger.info("rpicam::: jobRun(): Local daily output folder %s created.", self._locdir)

        except OSError as e:
            if e.errno == EEXIST:
                rpiLogger.debug("rpicam::: jobRun(): Local daily output folder %s already exist!", self._locdir)
                pass
            else:
                rpiLogger.error("rpicam::: jobRun(): Local daily output folder %s could not be created!\n%s\n", self._locdir, e)
                raise rpiBaseClassError(f"rpicam::: jobRun(): Local daily output folder {self._locdir} could not be created!", ERRCRIT)

        finally:
            self.image_name = self.imageFIFO.crtSubDir + '-' + time.strftime('%H%M%S', time.localtime()) + '-' + self._camid + '.jpg'
            self.image_path = os.path.join(self._locdir, self.image_name)


        ### Take a new snapshot and save the image locally
        self._camerrors = ''
        try:
            ### Reset list of cmd arguments
            self.cam_clistr.clear()

            ### Capture image
            if FAKESNAP:
                rpiLogger.debug("rpicam::: jobRun(): FAKESNAP Snapshot: %s", self.image_name)
                self._grab_cam = subprocess.Popen("touch " + self.image_path, stderr=subprocess.PIPE, stdout=subprocess.PIPE, shell=True)

                # Check return/errors
                self._camoutput, self._camerrors = self._grab_cam.communicate()

            elif RPICAM2:
                rpiLogger.debug("rpicam::: jobRun(): RPICAM2 Snapshot")

                # Set exif data
                crt_time = time.strftime('%Y:%m:%d %H:%M:%S', time.localtime())
                self._custom_exif['0th'][piexif.ImageIFD.DateTime] = crt_time
                self._custom_exif['Exif'][piexif.ExifIFD.DateTimeOriginal] = crt_time

                # Set camera exposure according to the 'dark' time threshold
                self._setCamExp_rpicam()

                # Start the camera
                self._camera.start(show_preview=False)
                time.sleep(1)

                # Get image metadata
                self._capture_metadata()
                rpiLogger.info("rpicam::: jobRun(): Capture metadata: %s", self._controls)

                # Capture image to memory
                stream = io.BytesIO()
                self._camera.capture_file(stream, format='jpeg')

                # Read stream to a PIL image
                #(buffer, ), metadata = camera.capture_buffers(["main"])
                #image = camera.helpers.make_image(buffer, _still_config["main"])
                stream.seek(0)
                image = Image.open(stream)

                # Calculate initial image brightness
                #self._grayscaleAverage(image)
                self._averagePerceived(image)

                # When in 'dark' time
                # Calculate image brightness and adjust exposure time if needed
                if self._dark_exp: # and not self._config['use_irl']:

                    # Recapture image with new exposure time if needed
                    if self._imgbr < 118 or \
                        self._imgbr > 138:

                        # Release the buffer (this capture could take a few seconds)
                        self.imageFIFO.releaseSemaphore()

                        # Exposure time (micro seconds)
                        rpiLogger.debug("rpicam::: jobRun(): Before: Br=%d, Ss=%dus", self._imgbr, self._controls["ExposureTime"])

                        # Re-capture the image with adjusted exposure time
                        self._camera.set_controls({"ExposureTime": int(self._controls["ExposureTime"]*(2 - float(self._imgbr)/128))}) 
                        time.sleep(1)
                        self._capture_metadata()
                        self._camera.capture_file(stream, format='jpeg')
                        stream.seek(0)
                        image = Image.open(stream)

                        # Re-calculate image brightness
                        self._averagePerceived(image)
                        rpiLogger.debug("rpicam::: jobRun(): After: Br=%d, Ss=%dus", self._imgbr, self._controls["ExposureTime"])

                        # Lock the buffer
                        self.imageFIFO.acquireSemaphore()

                # Apply +/-90 degree rotation with PIL (CCW)
                # Rotation with 180 degree is done in the camera configuration!
                if self._rotation in [90, -90, 270, -270]:
                    image = image.rotate(self._rotation, expand=True)
                
                # Add overlay text to the final image
                if self._config['use_ovltxt']:
                    draw = ImageDraw.Draw(image,'RGBA')
                    draw.rectangle([0,image.size[1]-20,image.size[0],image.size[1]], fill=(150,200,150,100))
                    sN = ': '
                    if self._dark_exp:
                        if self._config['use_irl']:
                            sN = ' (NI)' + sN
                        else:
                            sN = ' (N)' + sN
                    draw.text(
                        (2, image.size[1]-18),
                        f"{self._camid:s}{sN:s}{time.strftime('%b %d %Y, %H:%M:%S', time.localtime()):s}  "
                        f"AE:{self._controls['AeEnable']}, EV:{self._controls['ExposureValue']:.1f}, "
                        f"ET:{self._controls['ExposureTime']}, PB:{float(self._imgbr)/128:.1f}",
                        fill=(0,0,0,0),
                        font=self._TXTfont
                    )
                    #n_width, n_height = TXTfont.getsize('#XX')
                    #draw.text((image.size[0]-n_width-2,image.size[1]-18), '#XX', fill=(0,0,0,0), font=self._TXTfont)
                    del draw

                # Save image to the output file
                #camera.helpers.save(img=image, metadata, file_output=image_path, format='jpeg', exif_data=self._custom_exif)
                image.save(self.image_path, format='jpeg', quality=self._jpgqual, exif=piexif.dump(self._custom_exif))

                # Close BytesIO stream
                stream.close()

                # Set output indicators
                self._camoutput = self.image_path
                self._camerrors = ''

            elif LIBCAMERA:
                rpiLogger.debug("rpicam::: jobRun(): LIBCAMERA Snapshot")

                # See Camera software, https://www.raspberrypi.com/documentation/computers/camera_software.html#rpicam-still

                # Set camera exposure according to the 'dark' time threshold
                self._setCamExp_libcamera()

                # Generate the arguments
                self.cam_clistr.extend([
                    "rpicam-still", "--tuning-file", f"/usr/share/libcamera/ipa/rpi/vc4/{LIBCAMERA_JSON:s}", 
                    "-n", 
                    "--immediate"])
                self.cam_clistr.extend(self.camexp_cliargs) 
                self.cam_clistr.extend([ 
                    "--width", f"{self._resolution[0]}", "--height", f"{self._resolution[1]}", 
                    "-q", f"{self._jpgqual:n}", 
                    "--rotation", f"{self._rotation:n}", 
                    "-o", f"{self.image_path:s}"])
                
                # Capture image
                self._grab_cam = subprocess.Popen(self.cam_clistr, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
                #time.sleep(5)

                # Check return/errors
                #self.grab_cam.wait()
                self._camoutput, self._camerrors = self._grab_cam.communicate(timeout=10)

                #self._grab_cam = subprocess.run(self.cam_clistr, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
                #self._camoutput, self._camerrors = self._grab_cam.stdout, self._grab_cam.stderr

                # TODO: post-process to add text with OpenCV
                # https://www.raspberrypi.com/documentation/accessories/camera.html#post-processing
                # https://www.raspberrypi.com/documentation/accessories/camera.html#writing-your-own-post-processing-stages


            else:
                rpiLogger.debug("rpicam::: jobRun(): FSWEBCAM Snapshot")

                # Generate the arguments
                self.cam_clistr.extend(["fswebcam", 
                    "-d", "/dev/video0",
                    "-s brightness=", "50%",
                    "-s gain=", "32",
                    f"{self.image_path:s}"])

                # Capture image
                self._grab_cam = subprocess.Popen(self.cam_clistr, stderr=subprocess.PIPE, stdout=subprocess.PIPE, shell=True)

                ### Check return/errors
                self._camoutput, self._camerrors = self._grab_cam.communicate()

        except (OSError, TypeError, IOError) as e:
            rpiLogger.warning("rpicam::: jobRun(): Snapshot %s could not be created!\n%s", self.image_path, e)
            raise rpiBaseClassError(f"rpicam::: jobRun(): Snapshot {self.image_path} could not be created!", ERRLEV2)

        except subprocess.TimeoutExpired:
            rpiLogger.warning("rpicam::: jobRun(): Libcamera-still timeout!")
            self._grab_cam.kill()

        finally:

            ### Lock the buffer
            self.imageFIFO.acquireSemaphore()

            ### Check if the image file has been actually saved
            if os.path.exists(self.image_path):
                rpiLogger.info("rpicam::: jobRun(): Snapshot saved: %s", self.image_name)

                # Add image to deque (FIFO)
                self.imageFIFO.append(self.image_path)
                self.crtlenFIFO = len(self.imageFIFO)

            else:
                rpiLogger.warning("rpicam::: jobRun(): Snapshot NOT saved: %s!", self.image_name)
                rpiLogger.warning("rpicam::: jobRun(): List of args: %s", self.cam_clistr)
                if self._camerrors:
                    rpiLogger.debug("rpicam::: jobRun(): Error was: %s", self._camerrors.decode())

            ### Info about the FIFO buffer
            if self.crtlenFIFO > 0:
                rpiLogger.debug("rpicam::: jobRun(): imageFIFO[0...{self.crtlenFIFO-1}]: %s ... %s", self.imageFIFO[0], self.imageFIFO[-1])
            else:
                rpiLogger.debug("rpicam::: jobRun(): imageFIFO[]: empty")

            ### Update status
            self.statusUpdate = (self.name, self.crtlenFIFO)

            ### Release the buffer
            self.imageFIFO.releaseSemaphore()

            ### Close the picamera
            if self._camera is not None and RPICAM2:
                self._camera.stop()

            ### Switch off IR
            self._switchIR(False)


    def initClass(self):
        """"
        (re)Initialize the class.
        """
        ### Clean up camera and GPIO
        self._del_cam_gpio()
              
        ### Init the FIFO buffer
        self.imageFIFO.camID = self._config['cam_id']
        self.imageFIFO.clear()
        self.crtlenFIFO = 0

        ### Init GPIO ports, BCMxx pin. NO CHECK!
        self.IRLport = None
        self.PIRport = None
        if not FAKESNAP:
            if self._config['use_irl'] or self._config['use_pir']:
                try:
                    GPIO.setmode(GPIO.BCM)
                    rpiLogger.info("rpicam::: initClass(): GPIO BCM mode configured (%s)", GPIO.BCM)
                    if GPIO.getmode() is not None: 

                        if self._config['use_irl']:
                            self.IRLport = self._config['bcm_irlport']
                            GPIO.setup(self.IRLport, GPIO.OUT, initial=0)
                            rpiLogger.info("rpicam::: GPIO IRLport configured (BCM %d)", self.IRLport)
                        else:
                            self.IRLport = None
                            rpiLogger.warning("rpicam::: initClass(): GPIO IRLport is not used")  

                        if self._config['use_pir']:
                            self.PIRport = self._config['bcm_pirport']
                            self.pirTimeDelta = timedelta(seconds=self._config['pirtd_sec'])
                            GPIO.setup(self.PIRport, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
                            # The bouncetime is set to avoid quick signal level changes
                            # The larger and configurable detection delay is added in _pirRun
                            self.lastPirDetected = datetime.now()
                            GPIO.add_event_detect(self.PIRport, GPIO.RISING, callback=self._pirRun, bouncetime=500)
                            rpiLogger.info("rpicam::: initClass(): GPIO PIRport configured (BCM %d, %f sec intv.)", self.PIRport, self.pirTimeDelta)
                        else:
                            self.PIRport = None
                            rpiLogger.warning("rpicam::: GPIO PIRport is not used")  

                    else:
                        GPIO.cleanup()
                        rpiLogger.error("rpicam::: initClass(): GPIO.getmode() returned None!\n")   
                        raise rpiBaseClassError("rpicam::: initClass(): GPIO.getmode() returned None!", ERRCRIT)
                    
                except RuntimeError as e:
                    rpiLogger.error("rpicam::: initClass(): GPIO could not be configured!\n%s\n" , str(e))   
                    raise rpiBaseClassError("rpicam::: initClass(): GPIO could not be configured!", ERRCRIT)

            else:
                rpiLogger.warning("rpicam::: initClass(): GPIO is not used")   

        ### Reset flag indicating that PIR sensor has detected movement since last picture has been captured
        self.pirDetected.clear()

        ### Configuration for the image capture
        self._camera:Picamera2 = None
        self._metadata        = dict()
        self._camid           = self._config['cam_id']
        self._resolution      = tuple(self._config['image_res']) 
        self._rotation        = self._config['image_rot']
        self._jpgqual         = self._config['jpg_qual']

        # The dynamimcally configurable camera conbtrol parameters
        self._dynconfig_path         = CONTROLS_JSON
        self._dynconfig_lastmodified = 0
        self._dynconfig_exp          = dict()
        self._dynconfig_exp_loaded   = False
        self._valid_expkeys          = ['cam_expday', 'cam_expnight', 'cam_expnight-irl']

        ### Init the "dark" time flag and reference image brightness
        self._dark_exp = False
        self._imgbr    = 128

        ### Init the camera object
        if RPICAM2:
            # Picamera2 API, recommended since 2022!
            tuning = Picamera2.load_tuning_file(f"{LIBCAMERA_JSON:s}")
            self._camera = Picamera2(tuning=tuning)

            _still_config = self._camera.create_still_configuration()
            _still_config['main']['size'] = self._resolution

            # Set camera image rotation
            # Note: libcamera Transform does not support +/-90 degree rotation, so we apply it later with the PIL image (CCW)
            if self._rotation in [90, -270]:
                _orientation = 6
            elif self._rotation in [-90, 270]:
                _orientation = 8
            elif self._rotation == 180:
                _orientation = 3
                _still_config["transform"] = Transform(hflip=1, vflip=1)
            else:
                _orientation = 1

            self._camera.configure(_still_config)
            self._camera.options["quality"] = self._jpgqual

            # Set custom EXIF/TIFF tags
            # https://exiv2.org/tags.html
            # https://github.com/hMatoba/Piexif/blob/master/piexif/_exif.py
            # 0th IFD for primary image data (saved under TIFF data)
            # Exif IFD for Exif-specific attribute information (saved under EXIF data)
            # This data will be added to the output image when the image is captured
            self._custom_exif = {
                '0th': {
                            piexif.ImageIFD.Model: self._camera.camera_properties["Model"],
                            piexif.ImageIFD.Make: "Raspberry Pi",
                            piexif.ImageIFD.Software: RPICAMPY_VER,
                            piexif.ImageIFD.DateTime: time.strftime('%Y:%m:%d %H:%M:%S', time.localtime()),
                            piexif.ImageIFD.Artist: self._camid,
                            piexif.ImageIFD.ImageDescription: "Time-lapse with Rasberry Pi controlled (pi)camera2",
                            piexif.ImageIFD.Copyright: IMAGE_COPYRIGHT, 
                            piexif.ImageIFD.Orientation: 1, # This must be set to 1 in order to display correctly
                            piexif.ImageIFD.XResolution: (self._resolution[0],1),
                            piexif.ImageIFD.YResolution: (self._resolution[1],1),
                        },
                'Exif': {
                            piexif.ExifIFD.DateTimeOriginal: time.strftime('%Y:%m:%d %H:%M:%S', time.localtime()),
                        }
                }
            
            # Init the font to use in the overlay text
            self._TXTfont = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)

        ### Create output folder
        try:
            os.mkdir(self._config['image_dir'])
            self.imgSubDir = time.strftime('%d%m%y', time.localtime())
            rpiLogger.info("rpicam::: initClass(): Local output folder %s created.", self._config['image_dir'])
        except OSError as e:
            if e.errno == EEXIST:
                rpiLogger.info("rpicam::: initClass(): Local output folder %s already exist!", self._config['image_dir'])
                pass
            else:
                rpiLogger.error("rpicam::: initClass(): Local output folder %s could not be created!\n%s\n", self._config['image_dir'], e)
                raise rpiBaseClassError(f"rpicam::: initClass(): Local output folder {self._config['image_dir']} could not be created!", ERRCRIT)

        ### Fill in the fifo buffer with images found in the output directory
        ### Only the image files with the current date are listed!
        #imagelist_ref = sorted(glob.glob(self._config['image_dir'] + '/' + time.strftime('%d%m%y', time.localtime()) + '-*.jpg'))
        #self.imageFIFO.acquireSemaphore()
        #for img in imagelist_ref:
        #   if not img in self.imageFIFO:
        #       self.imageFIFO.append(img)
        #self.imageFIFO.releaseSemaphore()

        # Ephem parameters
        # The ephem.localtime() function converts a PyEphem date into a Python datetime object and locatimelizes it,
        # so that the resulting datetime object can be used with other Python libraries that expect dates and times
        # to be in local time. Note that the ephem.now() function returns the current date and time in UTC, so
        # if you want to use local time, you need to convert it using ephem.localtime().
        # The observer's latitude and longitude are specified
        # A negative value of horizon can be used when an observer is high off of the ground.
        self._sun = ephem.Sun()
        self._loc = ephem.Observer()
        self._loc.date = ephem.now()
        self._loc.lat = self._config['lat_lon'][0]
        self._loc.lon = self._config['lat_lon'][1]
        self._loc.pressure = 0
        self._loc.horizon = '-2:30'

#   def endDayOAM(self):
#       """
#       End-of-Day OAM procedure.
#       """

#   def endOAM(self):
#       """
#       End OAM procedure.
#       """

    def runCustomCmd(self, cmdstr: str) -> Dict[str, Any]:
        """
        Run a custom command with arguments extracted from cmdstr.

        Examples of cmdstr and corresponding actions:
            "get/jpg_qual" - get the current JPEG quality setting from self._config['jpg_qual']
            "get/cam_expday/*" - get all current 'daylight' camera exposure settings from self._config['cam_expday']
            "get/cam_expnight/brightness" - get the current 'dark' camera brightness setting from self._config['cam_expnight']
            "set/cam_expnight-irl/brightness/3" - set the 'dark' camera brightness setting to 3 in self._config['cam_expnight-irl']
            "set/image_res/1024/768" - set the image width to 1024 and height to 768 in self._config['image_res']
        """
        result = {}
        
        try:
            # Split command string into parts
            cmd_parts = cmdstr.split('/')
            
            if len(cmd_parts) < 2:
                raise ValueError("Invalid command format. At least two parts required: 'action/target'")
                
            action = cmd_parts[0]  # get or set
            if action not in ['get', 'set']:
                raise ValueError(f"Action '{action}' is invalid, must be 'get' or 'set'")

            target = cmd_parts[1]  # config key
            
            # Handle get commands
            if action == "get":

                if len(cmd_parts) == 2:
                    # Simple get command for parameter from self._config[target]
                    if target in self._config.keys():
                        result = {target: self._config[target]}
                    else:
                        raise KeyError(f"Target {target} not found in configuration")

                else:
                    # Get command for exposure parameters from self._config[target] (nested dict)
                    param = cmd_parts[2]  # parameter or *
                    
                    # Handle camera exposure settings
                    if target in self._valid_expkeys:
                        if param == '*':
                            # Return all settings for the target
                            result = self._config[target]
                        else:
                            # Return specific parameter value
                            if param in self._config[target].keys():
                                result = {param: self._config[target][param]}
                            else:
                                raise KeyError(f"Parameter '{param}' not found in '{target}'")
                    else:
                        raise KeyError(f"Target '{target}' not found in configuration")
                

            # Handle set commands
            elif action == "set":
                if len(cmd_parts) < 3:
                    raise ValueError("Invalid set command format")
                                    
                # Handle camera exposure settings (nested dict)
                if target in self._valid_expkeys:

                    param = cmd_parts[2]  # parameter to set
                    if len(cmd_parts) < 4:
                        raise ValueError("Set command requires a parameter value")

                    if param in self._config[target].keys():
                        value = cmd_parts[3] # parameter value to set

                        # Convert value to appropriate type
                        if isinstance(self._config[target][param], bool):
                            value = value.lower() == 'true'
                        elif isinstance(self._config[target][param], (int, float)):
                            value = type(self._config[target][param])(value)
                        else:
                            raise KeyError(f"Parameter '{param}' in '{target}' is invalid type")
    
                        with self.config_lock:
                            self._config[target][param] = value
    
                        result = {param: value}

                    else: 
                        raise KeyError(f"Parameter '{param}' not found in '{target}'")
                
                # Handle setting a simple parameter value
                elif target in self._config:
                    
                    # The number of parameters to set
                    if isinstance(self._config[target], list):
                        _n_param = len(self._config[target])
                    else:
                        _n_param = 1

                    if len(cmd_parts) != 2 + _n_param:
                        raise ValueError(f"Set command for '{target}' requires {_n_param} parameter value(s)")
                    
                    # Set the parameter value(s)
                    if _n_param == 1:
                        value = cmd_parts[2]
                        # Convert value to appropriate type
                        if isinstance(self._config[target], bool):
                            value = value.lower() == 'true'
                        elif isinstance(self._config[target], (int, float)):
                            value = type(self._config[target])(value)

                        with self.config_lock:
                            self._config[target] = value
                        
                        result = {target: value}

                    else:
                        values = []
                        for i in range(_n_param):
                            val = cmd_parts[2 + i]
                            # Convert value to appropriate type
                            if isinstance(self._config[target][i], bool):
                                val = val.lower() == 'true'
                            elif isinstance(self._config[target][i], (int, float)):
                                val = type(self._config[target][i])(val)
                            values.append(val)
    
                        with self.config_lock:
                            self._config[target] = values
                        
                        result = {target: values}
                                       
                else:
                    raise KeyError(f"Target '{target}' not found in configuration")
                

            # If using dynamic controls, save the updated configuration
            if self._config['use_dynctrl']:
                self._save_dynconfig()

        except (ValueError, KeyError, TypeError) as e:
            rpiLogger.error("rpicam::: Error in runCustomCmd!\n%s\n", str(e))
            result = {'error': str(e)}
            
        return result

    def _pirRun(self,c):
        """
        Set the flag indicating that PIR sensor has detected movement since last picture has been captured
        Mark a new detection only after a configurable delay from the last detection
        """
        tnow = datetime.now()
        if tnow - self.lastPirDetected >= self.pirTimeDelta:
            self.pirDetected.set()
            self.lastPirDetected = tnow
            rpiLogger.info("rpicam::: _pirRun(): PIR flag set")
        else:
            rpiLogger.debug("rpicam::: _pirRun(): PIR flag NOT set")
        

    def _setCamExp_libcamera(self):
        """
        Set camera exposure according to the 'daylight'/'dark' time threshold.
        Used only with LIBCAMERA!
        See Camera software, https://www.raspberrypi.com/documentation/computers/camera_software.html#rpicam-still
        TODO: Check & tune values!
        """
        if not LIBCAMERA:
            rpiLogger.warning("rpicam::: _setCamExp_libcamera() called when LIBCAMERA is not used!")
            return
        rpiLogger.debug("rpicam::: _setCamExp_libcamera() called with '%s' settings and use_irl=%s", \
                        'dark' if self._isDark() else 'daylight', \
                        'yes' if self._config['use_irl'] else 'no')

        # The 'dark' mode settings
        if self._isDark():
            if self._config['use_irl']:
                self.gain       = 4.0
                self.contrast   = 1.5 
                self.brightness = 20/50  
            else:
                self.gain       = 8.0
                self.contrast   = 1.3
                self.brightness = 20/50                    
                #self.framerate = Fraction(1, 2)
                self.shutter_speed = 5000000

            self._switchIR(True)
            self._dark_exp = True
        else:
            # The 'daylight' default settings
            self.shutter_speed = None
            self.awb_mode      = 'auto'
            self.exposure_mode = 'normal'
            self.gain       = 1.0 # ISO = 100 * analog gain (V1 camera)
            self.contrast   = 1.2 # 0 ... 1 ...    
            self.brightness = 0   #-1 ... 0 ... +1
            self.saturation = 1.0 # 0 ... 1 ...
            self.ev         = 0 # -10 ... 0 ... 10
            self.metering   = 'average'

            self._switchIR(False)
            self._dark_exp = False

        # Set the list with the parameter values
        self.camexp_cliargs = [
            "--awb", f"{self.awb_mode:s}",
            "--gain", f"{self.gain}",
            "--exposure", f"{self.exposure_mode:s}",
            "--contrast", f"{self.contrast}",
            "--brightness", f"{self.brightness}",
            "--saturation", f"{self.saturation}",
            "--ev", f"{self.ev}",
            "--metering", f"{self.metering:s}",
        ]
        if self.shutter_speed is not None:
            self.camexp_cliargs.extend([
                "--shutter", f"{self.shutter_speed}"
            ])


    def _setCamExp_rpicam(self):
        """
        Set camera exposure according to the 'daylight'/'dark' time periods.
        Used only with RPICAM2!
        See Apendix C in Picamera2 API documentation. 
        """
        if not RPICAM2:
            rpiLogger.warning("rpicam::: _setCamExp_rpicam() called when RPICAM2 is not used!")
            return
        rpiLogger.debug("rpicam::: _setCamExp_rpicam() called with '%s' settings and use_irl=%s", \
                        'dark' if self._isDark() else 'daylight', \
                        'yes' if self._config['use_irl'] else 'no')
                        
        if self._isDark():
            # The 'dark' mode settings
            if self._config['use_irl']:
                self._check_dynconfig('cam_expnight-irl')
                self._set_controls('cam_expnight-irl')
            else:
                self._check_dynconfig('cam_expnight')
                self._set_controls('cam_expnight')

            self._switchIR(True)
            self._dark_exp = True

        else:
            # The 'daylight' default setting 
            self._check_dynconfig('cam_expday')
            self._set_controls('cam_expday')

            self._switchIR(False)
            self._dark_exp = False


        # The following code is for picamera V1 API
        # and is kept for reference only, it is not to be used anymore

        # # The 'daylight' default settings
        # self._camera.awb_mode = 'auto'
        # self._camera.iso = 0
        # self._camera.contrast = 30
        # self._camera.brightness = 50
        # self._camera.exposure_mode = 'auto'
        # time.sleep(2)
        # self._dark_exp = False
    
        # # The 'dark' mode settings
        # if self._isDark():
        #     self._dark_exp = True
        #     if self._config['use_irl']:
        #         self._camera.awb_mode = 'auto'
        #         self._camera.iso = 0
        #         self._camera.contrast = 50 #-100 ... 0 ... 100
        #         self._camera.brightness = 70 #0 ... 50 ... 100
        #         self._camera.exposure_mode = 'auto'
        #         time.sleep(2)
        #     else:
        #         self._camera.awb_mode = 'auto'
        #         self._camera.iso = 800
        #         self._camera.contrast = 30
        #         self._camera.brightness = 70
        #         #self._camera.framerate = Fraction(1, 2)
        #         self._camera.exposure_mode = 'off'
        #         #self._camera.meter_mode = 'spot'
        #         self._camera.shutter_speed = 5000000
        #         time.sleep(5)
                
    def _set_controls(self, exp_cfg:str = ''):
        """ 
        Set the camera controls parameter _c to value _v
        where _c and _v are the keys and values in the self._config[exp_cfg] dict.
        Only valid exp_cfg keys listed in self._valid_expkeys are considered.
        """
        if exp_cfg in self._valid_expkeys:
            with self._camera.controls as ctrl:
                for _c, _v in self._config[exp_cfg].items():
                    if isinstance(_v, bool) or isinstance(_v, float) or isinstance(_v, int):
                        #self._camera.set_controls({_c: _v})
                        ctrl.__setattr__(_c, _v)
                    elif isinstance(_v, str) and _c in ['AwbMode', 'AeExposureMode', 'AeMeteringMode']:
                        #self._camera.set_controls({_c: eval(f"controls.{_c}Enum.{_v}")})
                        ctrl.__setattr__(_c, eval(f"controls.{_c}Enum.{_v}"))

            time.sleep(0.5)

    def _load_dynconfig(self):
        """ 
        Load the dynamic camera configuration JSON file 
        if the file exists and has been mmodified since last loaded. 
        If the file does not exist, a JSOn file is created from the 
        current configuration values loaded from rpiconfig.yaml.
        """
        try:
            self._dynconfig_exp_loaded = False
            if os.path.exists(self._dynconfig_path):
                _crt_modified = os.path.getmtime(self._dynconfig_path)
                if _crt_modified != self._dynconfig_lastmodified:
                    with open(self._dynconfig_path, "r") as f:
                        self._dynconfig_exp = json.load(f)
                    self._dynconfig_lastmodified = _crt_modified
                    self._dynconfig_exp_loaded = True
                    rpiLogger.info("rpicam::: _load_dynconfig(): Dynamic camera controls configuration file %s loaded (last modified %s).", self._dynconfig_path, time.ctime(_crt_modified))
            else:
                self._save_dynconfig()

        except (json.JSONDecodeError, FileNotFoundError, ValueError) as e:
            rpiLogger.error("rpicam::: _load_dynconfig(): Error loading dynamic camera controls configuration file %s!\n%s\n", self._dynconfig_path, str(e))
            raise rpiBaseClassError(f"rpicam::: _load_dynconfig(): Error loading dynamic camera controls configuration file {self._dynconfig_path}!", ERRCRIT)
    
    def _save_dynconfig(self):
        """ 
        Save the dynamic camera configuration JSON file. 
        All the current values are saved.
        """
        try:
            self._dynconfig_exp = dict()
            for _exp_k in self._valid_expkeys:
                self._dynconfig_exp[_exp_k] = self._config[_exp_k]

            with open(self._dynconfig_path, "w") as f:
                json.dump(self._dynconfig_exp, f, indent=2)
            self._dynconfig_lastmodified = os.path.getmtime(self._dynconfig_path)
            rpiLogger.info("rpicam::: _save_dynconfig(): Dynamic camera controls configuration file %s saved (last modified %s).", self._dynconfig_path, time.ctime(self._dynconfig_lastmodified))

        except (FileNotFoundError, ValueError, KeyError) as e:
            rpiLogger.error("rpicam:::Error saving dynamic camera controls configuration file %s!\n%s\n", self._dynconfig_path, str(e))
            raise rpiBaseClassError(f"rpicam::: _save_dynconfig(): Error saving dynamic camera controls configuration file {self._dynconfig_path}!", ERRCRIT)  
        
    def _check_dynconfig(self, exp_cfg:str = ''):
        """ 
        Check, load and copy the dynamic camera configurations from the JSON file to self._config dict. 
        When exp_cfg (key) is specified only the corresponding parameters are copied to self._config dict.
        """
        self._dynconfig_exp_loaded = False
        if self._config['use_dynctrl']:

            # Load the configuration from JSON
            # if the file exists and has been modified since last loaded
            self._load_dynconfig()

            if self._dynconfig_exp and self._dynconfig_exp_loaded:
                # The loaded dict is expected to contain one or more of the keys listed in self._valid_expkeys, 
                # each having a sub-dict as value.
                # The sub-dict under any of these keys, if the key is present, will replace the corresponding values 
                # in self._config[key] or self._config[exp_cfg] when exp_cfg key is specified.
                # NOTE: There is no check of the a tuple keys/values in the copied sub-dicts!
                with self.config_lock:
                    if exp_cfg == '':
                        for _exp_k in self._dynconfig_exp.keys():
                            if _exp_k in self._valid_expkeys:
                                self._config[_exp_k] = self._dynconfig_exp[_exp_k]
                    else:
                        if exp_cfg in self._dynconfig_exp.keys() and exp_cfg in self._valid_expkeys:
                            self._config[exp_cfg] = self._dynconfig_exp[exp_cfg]


    def _capture_metadata(self):
        """ 
        Capture all the metadata from the camera. 
        Stores the selected control parameters in self._controls dict.
        Used only with RPICAM2!
        """
        if self._camera is not None and RPICAM2:
            self._metadata = self._camera.capture_metadata()
            self._controls = {c: self._metadata[c] for c in ["ExposureTime", "Brightness", "AeEnable"]} #"ExposureValue"
        else:
            rpiLogger.warning("rpicam::: _capture_metadata(): Camera metadata cannot be retrieved when RPICAM2 is not set!")
    
    def _isDark(self):
        """ Determine if current time is in the "dark" period. """

        # Check the current time against the (auto or manual/fixed) 'dark' time period
        if (self._config['start_dark_hour'] is None ) or (self._config['stop_dark_hour'] is None):
            # Determine current 'dark' time period using ephem
            # self._loc.date = time.strftime('%Y/%m/%d %H:%M:%S',time.localtime())
            # _ps = list(self._loc.previous_setting(self._sun).tuple())
            # # Set seconds to zero and extend to 9 elements
            # _ps.pop()  
            # _ps.extend([0,0,0,time.localtime().tm_isdst])
            # _nr = list(self._loc.next_rising(self._sun).tuple())
            # _nr.pop() 
            # _nr.extend([0,0,0,time.localtime().tm_isdst])
            # # Convert to local time, considering timezone offset
            # _tdark_start = time.localtime(time.mktime(tuple(_ps)) - time.timezone)
            # _tdark_stop = time.localtime(time.mktime(tuple(_nr)) - time.timezone)
            
            rpiLogger.debug("rpicam::: _isDark(): Auto 'dark' time period")
                           
            # The ephem.localtime() function converts a PyEphem date into a Python datetime object and locatimelizes it
            self._loc.date = ephem.now()
            _ps = ephem.localtime(self._loc.previous_setting(self._sun))
            _nr = ephem.localtime(self._loc.next_rising(self._sun))

            # Extract hour and minute values
            _start_dark_hour = _ps.hour
            _start_dark_min  = _ps.minute
            _stop_dark_hour  = _nr.hour
            _stop_dark_min   = _nr.minute

        else:
            rpiLogger.debug("rpicam::: _isDark(): Manual 'dark' time period")

            # Manual/fixed 'dark' time period was configured
            _start_dark_hour = self._config['start_dark_hour']
            _start_dark_min  = self._config['start_dark_min']
            _stop_dark_hour  = self._config['stop_dark_hour']
            _stop_dark_min   = self._config['stop_dark_min']

        rpiLogger.debug("rpicam::: _isDark(): 'start_dark' time: %02d:%02d", _start_dark_hour, _start_dark_min)
        rpiLogger.debug("rpicam::: _isDark(): 'stop_dark'  time: %02d:%02d", _stop_dark_hour, _stop_dark_min)

        self._tlocal = time.localtime()
        self._tdark_start = time.mktime((self._tlocal.tm_year, self._tlocal.tm_mon, self._tlocal.tm_mday,
                    _start_dark_hour, _start_dark_min, 0,
                    self._tlocal.tm_wday, self._tlocal.tm_yday, self._tlocal.tm_isdst ))
        self._tdark_stop = time.mktime((self._tlocal.tm_year, self._tlocal.tm_mon, self._tlocal.tm_mday,
                    _stop_dark_hour, _stop_dark_min, 0,
                    self._tlocal.tm_wday, self._tlocal.tm_yday, self._tlocal.tm_isdst ))

        return (time.time() >= self._tdark_start) or (time.time() <= self._tdark_stop)


    def _switchIR(self, bONOFF):
        """ Switch ON/OFF the IR lights. """
        if self._config['use_irl']:
            if bONOFF:
                rpiLogger.debug("rpicam::: _switchIR(): Switching ON the IR lights (BCM %d)", self.IRLport)
                GPIO.output(self.IRLport, GPIO.HIGH)
            else:
                rpiLogger.debug("rpicam::: _switchIR(): Switching OFF the IR lights (BCM %d)", self.IRLport)
                GPIO.output(self.IRLport, GPIO.LOW)


    ### The following 4 functions are based on:
    # https://github.com/andrevenancio/brightnessaverage
    # by Andre Venancio, June 2014
    # The calculated brightness value can be used to adjust the camera shutter speed:
    # ss = ss*(2 - self._imgbr/128)

    def _grayscaleAverage(self, image):
        """ Convert image to greyscale, return average pixel brightness. """
        if not self._config['use_irl']:
            # Upper ~1/3 of the image is masked out (black), not used in the statistics
            mask = Image.new('1', (image.size[0], image.size[1]))
            draw = ImageDraw.Draw(mask,'1')
            draw.rectangle([0,int(image.size[1]/3),image.size[0],image.size[1]],fill=255)
            #draw.rectangle([0,0,410,356],fill=255)
            del draw

            stat = ImageStat.Stat(image.convert('L'), mask=mask)

        else:
            stat = ImageStat.Stat(image.convert('L'))

        self._imgbr = stat.mean[0]


    def _grayscaleRMS(self, image):
        """ Convert image to greyscale, return RMS pixel brightness. """
        stat = ImageStat.Stat(image.convert('L'))
        self._imgbr = stat.rms[0]

    def _averagePerceived(self, image):
        """ Average pixels, then transform to "perceived brightness". """
        if not self._config['use_irl']:
            # Upper ~1/3 of the image is masked out (black), not used in the statistics
            mask = Image.new('1', (image.size[0], image.size[1]))
            draw = ImageDraw.Draw(mask,'1')
            draw.rectangle([0,int(image.size[1]/3),image.size[0],image.size[1]],fill=255)
            #draw.rectangle([0,0,410,356],fill=255)
            del draw

            stat = ImageStat.Stat(image, mask=mask)

        else:
            stat = ImageStat.Stat(image)

        r,g,b = stat.mean
        self._imgbr = math.sqrt(0.241*(r**2) + 0.691*(g**2) + 0.068*(b**2))

    def _rmsPerceivedBrightness(self, image):
        """ RMS of pixels, then transform to "perceived brightness". """
        stat = ImageStat.Stat(image)
        r,g,b = stat.rms
        self._imgbr = math.sqrt(0.241*(r**2) + 0.691*(g**2) + 0.068*(b**2))


#   def _cvcamimg(self, output_file='test.jpg'):
        ### Open camera and get an image
        # camera = cv2.VideoCapture(0)
        # retval, img = camera.read()
        # if retval:
        ### Calculate brightness
        # br = img.sum(axis=2) / img.shape[2]
        # med_br = np.percentile(br,50)

        ### Adjust camera brightness
        ### See cv2.cv.CV_CAP_PROP_*
        ### Use med_br to set xb and/or xg = 0 .. 1
        # camera.set(cv2.cv.CV_CAP_PROP_BRIGHTNESS, xb)
        # camera.set(cv2.cv.CV_CAP_PROP_GAIN, xg)

        ### Get a new image and save it
        # retval, img = camera.read()
        # if retval:
        # cv2.imwrite(output_file, img, [cv2.cv.CV_IMWRITE_JPEG_QUALITY, 95])

        ### Release camera
        # # camera.release()
        # del(camera)
