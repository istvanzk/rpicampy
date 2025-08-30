# -*- coding: utf-8 -*-
"""
    Time-lapse with Rasberry Pi controlled camera
    Copyright (C) 2016-2021 Istvan Z. Kovacs

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

Implements the rpiCam class, to run and control a:
    - Raspberry PI camera using the raspistill utility or
    - Raspberry PI camera usingthe picamera module, or
    - Web camera using fswebcam utility.
GPIO ON/OFF control of an IR/VL reflector for night imaging.
"""
import os
from errno import EEXIST
import glob
import time
from datetime import datetime, timezone, timedelta
import subprocess
import ephem
import math
from threading import Event

### The rpi(cam)py modules
import rpififo
from rpilogger import rpiLogger
from rpibase import rpiBaseClass, rpiBaseClassError
from rpibase import ERRCRIT, ERRLEV2, ERRLEV1, ERRLEV0, ERRNONE

### Camera input to use
# When none selected, then the fswebcam -d /dev/video0 is attemped to be used to capture an image
# FAKESNAP generates an empty file!
FAKESNAP   = False

# The real image 'back-end' to use
# RPICAM2 is using the Picamera2 API and is the preferred/recommended option since 2022
# See https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf)
RPICAM2    = True
# LIBCAMERA is using the rpicam-still (from rpicam-apps installed with picamera2) since 2022 
# See https://www.raspberrypi.com/documentation/computers/camera_software.html#rpicam-still
LIBCAMERA  = False
# The use of picamera (v1) API is depracated since 2022! Use picamera2 (v2) instead!
RPICAM     = False

# LIBCAMERA_JSON has to be set to the JSON file name corresponding to the used camera (see docs above)
LIBCAMERA_JSON = "ov5647_noir.json" # Cam V1 Noir: dtoverlay=ov5647 in /boot/config.txt
#LIBCAMERA_JSON = "imx219.json" # Cam V2: dtoverlay=imx219 in /boot/config.txt

if FAKESNAP:
    # Dummy (no image capture!)
    LIBCAMERA  = False
    RPICAM2    = False
    RPICAM     = False
    rpiLogger.warning("rpicam::: The FAKESNAP option is used!")

elif RPICAM2:
    # Picamera2 (V2) API
    try:
        from picamera2 import Picamera2, Preview
        from libcamera import controls, Transform
    except ImportError:
        rpiLogger.error("rpicam::: The picamera2 (v2) module could not be loaded!")
        RPICAM2 = False

    import piexif
    import io
    from PIL import Image, ImageDraw, ImageFont, ImageStat

elif RPICAM:
    # PIcamera (V1) API
    rpiLogger.warning("rpicam::: The use of picamera (v1) module is deprecated since 2022! Use picamera2 (v2) instead!")
    try:
        import picamera
    except ImportError:
        rpiLogger.error("rpicam::: The picamera (v1) module could not be loaded!")
        RPICAM = False

    #from fractions import Fraction
    import io
    from PIL import Image, ImageDraw, ImageFont, ImageStat

### GPIO
if LIBCAMERA or RPICAM2 or RPICAM:
    # Requires rpi-lgpio compatibility package for rpi.gpio on kernels which support /dev/gpiochipX
    # See https://rpi-lgpio.readthedocs.io/en/latest/index.html
    try:
        import RPi.GPIO as GPIO
        rpiLogger.info(f"rpicam::: The RPi.GPIO (rpi-lgpio) module is used. {GPIO.RPI_INFO}")
    except NotImplementedError as e:
        rpiLogger.warning("rpicam::: If the error below reads 'This module does not understand old-style revision codes'")
        rpiLogger.warning("rpicam::: then see https://rpi-lgpio.readthedocs.io/en/latest/differences.html#pi-revision")
        rpiLogger.error(f"rpicam::: The RPi.GPIO (rpi-lgpio) module could not be initialized! {e}\n")
        raise rpiBaseClassError(f"rpicam::: The RPi.GPIO (rpi-lgpio) module could not be initialized! {e}", ERRCRIT)
    except ImportError:
        rpiLogger.error("rpicam::: The RPi.GPIO (rpi-lgpio) module could not be loaded!")
        raise rpiBaseClassError(f"rpicam::: The RPi.GPIO (rpi-lgpio) module could not be loaded!", ERRCRIT)
else:
    rpiLogger.warning("rpicam::: The RPi.GPIO module is not used!")
    raise rpiBaseClassError(f"rpicam::: The RPi.GPIO module is not used!", ERRCRIT)

if not(FAKESNAP or LIBCAMERA or RPICAM2 or RPICAM):
    rpiLogger.error("rpicam::: No camera input selected! Exiting!")
    raise rpiBaseClassError("rpicam::: No camera input selected! Exiting!", ERRCRIT)

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

        ### Get the Dbx error event
        self._eventDbErr    = rpi_events.eventErrList["DBXJob"]

        ### Get the custom config parameters
        self._config = rpi_config

        ### The FIFO buffer (deque)
        self.imageFIFO = rpififo.rpiFIFOClass([], self._config['list_size'])

        ### The flag indicating that PIR sensor has detected movement since last picture has been captured
        self.pirDetected = Event()
        self.pirDetected.clear()
        self.pirTimeDelta = None
        self.lastPirDetected = None

        ### Camera capture parameters
        self.camexp_list     = list()
        self.cmd_str         = list()

        ### Init base class
        super().__init__(name, rpi_apscheduler, rpi_events)

    def __repr__(self):
        return "<%s (name=%s, rpi_apscheduler=%s, rpi_events=dict(), rpi_config=%s, dbuff_rpififo=%s)>" % (self.__class__.__name__, self.name, self._sched, self._config, self.imageFIFO)

    def __str__(self):
        msg = super().__str__()
        return "%s::: %s, config: %s, FAKESNAP: %s, LIBCAMERA: %s, RPiCAM: %s\nimageFIFO: %s\n%s" % \
            (self.name, self.camid, self._config, FAKESNAP, LIBCAMERA, RPICAM, self.imageFIFO, msg)

    def __del__(self):
        ### Clean up Camera and GPIO
        self._del_cam_gpio()

        ### Clean base class
        super().__del__()

    def _del_cam_gpio(self):
        try:
            ### Close and delete the picamera object
            if self._camera is not None:
                if RPICAM:
                    self._camera.close()
                elif RPICAM2:
                    self._camera.stop()
                del self._camera
                self._camera = None

            ### Clean up GPIO on exit
            if not FAKESNAP and GPIO.getmode() is not None:
                if self._config['use_pir'] == 1:
                    GPIO.remove_event_detect(self.PIRport)

                if self._config['use_irl'] == 1:
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
        if self._config['use_pir'] == 1:
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
            rpiLogger.info(f"{self.name}::: Local daily output folder {self._locdir} created.")

        except OSError as e:
            if e.errno == EEXIST:
                rpiLogger.debug(f"{self.name}::: Local daily output folder {self._locdir} already exist!")
                pass
            else:
                raise rpiBaseClassError(f"{self.name}::: jobRun(): Local daily output folder {self._locdir} could not be created!", ERRCRIT)

        finally:
            self.image_name = self.imageFIFO.crtSubDir + '-' + time.strftime('%H%M%S', time.localtime()) + '-' + self.camid + '.jpg'
            self.image_path = os.path.join(self._locdir, self.image_name)


        ### Take a new snapshot and save the image locally
        try:
            ### Switch ON/OFF IR
            if (not FAKESNAP) and (self._config['use_irl'] == 1):
                self._switchIR(self._isDark())

            ### Reset list of cmd arguments
            self.cmd_str.clear()

            ### Capture image
            if FAKESNAP:
                rpiLogger.debug('Faking snapshot: ' + self.image_name)
                self._grab_cam = subprocess.Popen("touch " + self.image_path, stderr=subprocess.PIPE, stdout=subprocess.PIPE, shell=True)

                # Check return/errors
                self._camoutput, self._camerrors = self._grab_cam.communicate()

            elif RPICAM2:
                # Note: Picamera2 API is the recommended option since 2022!

                # Set exif data
                crt_time = time.strftime('%Y:%m:%d %H:%M:%S', time.localtime())
                self._custom_exif['0th'][piexif.ImageIFD.DateTime] = crt_time
                self._custom_exif['Exif'][piexif.ExifIFD.DateTimeOriginal] = crt_time

                # Set camera exposure according to the 'dark' time threshold
                self._setCamExp()

                # Start the camera
                self._camera.start() # pyright: ignore[reportOptionalMemberAccess]
                time.sleep(5)

                # Capture image to memory
                stream = io.BytesIO()
                self._camera.capture_file(stream, format='jpeg') # pyright: ignore[reportOptionalMemberAccess]

                # Read stream to a PIL image
                #(buffer, ), metadata = camera.capture_buffers(["main"])
                #image = camera.helpers.make_image(buffer, _still_config["main"])
                stream.seek(0)
                image = Image.open(stream)

                # When in 'dark' time
                # Calculate brightness and adjust shutter speed when not using IR light
                if self.bDarkExp:
                    if self._config['use_irl'] == 0:

                        # Calculate brightness
                        #self._grayscaleAverage(image)
                        self._averagePerceived(image)

                        # Recapture image with new shutter speed if needed
                        if self.imgbr < 118 or \
                            self.imgbr > 138:

                            # Release the buffer (this capture could take a few seconds)
                            self.imageFIFO.releaseSemaphore()

                            # Shutter speed (micro seconds)
                            ss = self._camera.camera_controls["ExposureTime"] # pyright: ignore[reportOptionalMemberAccess]
                            rpiLogger.debug('Before: Br=%d, Ss=%dus' % (self.imgbr, ss))

                            # Re-capture the picture
                            time.sleep(3)
                            self._camera.set_controls({"ExposureTime": int(ss*(2 - float(self.imgbr)/128))}) # pyright: ignore[reportOptionalMemberAccess]
                            self._camera.capture_file(stream, format='jpeg') # pyright: ignore[reportOptionalMemberAccess]
                            stream.seek(0)
                            image = Image.open(stream)

                            # Re-calculate brightness
                            self._averagePerceived(image)
                            rpiLogger.debug('After: Br=%d, Ss=%dus' % (self.imgbr, self._camera.camera_controls["ExposureTime"]))

                            # Lock the buffer
                            self.imageFIFO.acquireSemaphore()

                # Apply +/-90 degree rotation with PIL (CCW)
                if self.rotation in [90, -90, 270, -270]:
                    image = image.rotate(self.rotation, expand=True)
                
                # Add overlay text to the final image
                draw = ImageDraw.Draw(image,'RGBA')
                draw.rectangle([0,image.size[1]-20,image.size[0],image.size[1]], fill=(150,200,150,100))
                sN = ': '
                if self.bDarkExp:
                    if self._config['use_irl'] == 1:
                        sN = ' (NI)' + sN
                    else:
                        sN = ' (N)' + sN
                draw.text((2,image.size[1]-18), f"{self.camid:s}{sN:s}{time.strftime('%b %d %Y, %H:%M', time.localtime()):s}", fill=(0,0,0,0), font=self._TXTfont)
                #n_width, n_height = TXTfont.getsize('#XX')
                #draw.text((image.size[0]-n_width-2,image.size[1]-18), '#XX', fill=(0,0,0,0), font=self._TXTfont)
                del draw

                # Save image to the output file
                #camera.helpers.save(img=image, metadata, file_output=image_path, format='jpeg', exif_data=self._custom_exif)
                image.save(self.image_path, format='jpeg', quality=self.jpgqual, exif=piexif.dump(self._custom_exif))

                # Close BytesIO stream
                stream.close()

                # Set output indicators
                self._camoutput = self.image_path
                self._camerrors = ''

            elif LIBCAMERA:
                # See Camera software, https://www.raspberrypi.com/documentation/computers/camera_software.html#rpicam-still

                # Set camera exposure according to the 'dark' time threshold
                self._setCamExp()

                # Generate the arguments
                self.cmd_str.extend([
                    "rpicam-still", "--tuning-file", f"/usr/share/libcamera/ipa/rpi/vc4/{LIBCAMERA_JSON:s}", 
                    "-n", 
                    "--immediate"])
                self.cmd_str.extend(self.camexp_list) 
                self.cmd_str.extend([ 
                    "--width", f"{self.resolution[0]}", "--height", f"{self.resolution[1]}", 
                    "-q", f"{self.jpgqual:n}", 
                    "--rotation", f"{self.rotation:n}", 
                    "-o", f"{self.image_path:s}"])
                
                # Capture image
                self._grab_cam = subprocess.Popen(self.cmd_str, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
                #time.sleep(5)

                # Check return/errors
                #self.grab_cam.wait()
                self._camoutput, self._camerrors = self._grab_cam.communicate(timeout=10)

                #self._grab_cam = subprocess.run(self.cmd_str, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
                #self._camoutput, self._camerrors = self._grab_cam.stdout, self._grab_cam.stderr

                # TODO: post-process to add text with OpenCV
                # https://www.raspberrypi.com/documentation/accessories/camera.html#post-processing
                # https://www.raspberrypi.com/documentation/accessories/camera.html#writing-your-own-post-processing-stages


            elif RPICAM:
                # Note: V1 API is deprecated since 2022!
                # https://picamera.readthedocs.io/en/release-1.13/api_camera.html

                # Set camera exposure according to the 'dark' time threshold
                self._setCamExp()

                # Create the in-memory stream
                stream = io.BytesIO()

                # Camera warm-up time and capture
                self.cmd_str.extend(["format", "jpeg", "quality", f"{self.imgqual}"])
                self._camera.capture(stream, format='jpeg', quality=self.imgqual)

                # Read stream to a PIL image
                stream.seek(0)
                image = Image.open(stream)

                # When in 'dark' time
                # Calculate brightness and adjust shutter speed when not using IR light
                sN = ': '
                if self.bDarkExp:
                    sN = 'n' + sN

                    if self._config['use_irl'] == 0:

                        # Calculate brightness
                        #self._grayscaleAverage(image)
                        self._averagePerceived(image)

                        # Recapture image with new shutter speed if needed
                        if self.imgbr < 118 or \
                            self.imgbr > 138:

                            # Release the buffer (this capture could take a few seconds)
                            self.imageFIFO.releaseSemaphore()

                            # Shutter speed (micro seconds)
                            ss = self._camera.shutter_speed
                            rpiLogger.debug('Before: Br=%d, Ss=%dus' % (self.imgbr, ss))

                            # Re-capture the picture
                            time.sleep(3)
                            self._camera.shutter_speed = int(ss*(2 - float(self.imgbr)/128))
                            self._camera.capture(stream, format='jpeg')
                            stream.seek(0)
                            image = Image.open(stream)

                            # Re-calculate brightness
                            self._averagePerceived(image)
                            rpiLogger.debug('After: Br=%d, Ss=%dus' % (self.imgbr, self._camera.shutter_speed))

                            # Lock the buffer
                            self.imageFIFO.acquireSemaphore()


                # Add overlay text to the final image
                draw = ImageDraw.Draw(image,'RGBA')
                draw.rectangle([0,image.size[1]-20,image.size[0],image.size[1]], fill=(150,200,150,100))
                draw.text((2,image.size[1]-18), self.camid + sN + time.strftime('%b %d %Y, %H:%M', time.localtime()), fill=(0,0,0,0), font=self._TXTfont)
                #n_width, n_height = TXTfont.getsize('#XX')
                #draw.text((image.size[0]-n_width-2,image.size[1]-18), '#XX', fill=(0,0,0,0), font=self._TXTfont)
                del draw

                # Save image and close the stream
                image.save( self.image_path, format='jpeg', quality=95 )
                #image.close()

                # Close BytesIO stream
                stream.close()

                # Set output indicators
                self._camoutput = self.image_path
                self._camerrors = ''

            else:

                # Generate the arguments
                self.cmd_str.extend(["fswebcam", 
                    "-d", "/dev/video0",
                    "-s brightness=", "50%",
                    "-s gain=", "32",
                    f"{self.image_path:s}"])

                # Capture image
                self._grab_cam = subprocess.Popen(self.cmd_str, stderr=subprocess.PIPE, stdout=subprocess.PIPE, shell=True)

                ### Check return/errors
                self._camoutput, self._camerrors = self._grab_cam.communicate()

        except OSError as e:
            raise rpiBaseClassError(f"{self.name}::: jobRun(): Snapshot {self.image_path} could not be created!\n{e}", ERRLEV2)

        except subprocess.TimeoutExpired:
            rpiLogger.warning(f"{self.name}::: jobRun(): Libcamera-still timeout!")
            self._grab_cam.kill()
            self._camoutput, self._camerrors = self._grab_cam.communicate()

        finally:

            ### Lock the buffer
            self.imageFIFO.acquireSemaphore()

            ### Check if the image file has been actually saved
            if os.path.exists(self.image_path):
                rpiLogger.info(f"{self.name}::: jobRun(): Snapshot saved: {self.image_name:s}")

                # Add image to deque (FIFO)
                self.imageFIFO.append(self.image_path)
                self.crtlenFIFO = len(self.imageFIFO)

            else:
                rpiLogger.warning(f"{self.name}::: jobRun(): Snapshot NOT saved: {self.image_name:s}!")
                rpiLogger.warning(f"{self.name}::: jobRun(): List of args: {self.cmd_str}")
                rpiLogger.debug(f"{self.name}::: jobRun(): Error was: {self._camerrors.decode()}")

            ### Info about the FIFO buffer
            if self.crtlenFIFO > 0:
                rpiLogger.debug(f"{self.name}::: jobRun(): imageFIFO[0...{self.crtlenFIFO-1}]: {self.imageFIFO[0]} ... {self.imageFIFO[-1]}")
            else:
                rpiLogger.debug(f"{self.name}::: jobRun(): imageFIFO[]: empty")

            ### Update status
            self.statusUpdate = (self.name, self.crtlenFIFO)

            ### Release the buffer
            self.imageFIFO.releaseSemaphore()

            ### Close the picamera
            if self._camera is not None:
                if RPICAM:
                    self._camera.close()
                elif RPICAM2:
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
        self.imageFIFO.camID = self._config['image_id']
        self.imageFIFO.clear()
        self.crtlenFIFO = 0

        ### Init GPIO ports, BCMxx pin. NO CHECK!
        self.IRLport = None
        self.PIRport = None
        if not FAKESNAP:
            if self._config['use_irl'] == 1 or self._config['use_pir'] == 1:
                try:
                    GPIO.setmode(GPIO.BCM)
                    rpiLogger.info(f"{self.name}::: GPIO BCM mode configured ({GPIO.BCM})")
                    if GPIO.getmode() is not None: 

                        if self._config['use_irl'] == 1:
                            self.IRLport = self._config['bcm_irlport']
                            GPIO.setup(self.IRLport, GPIO.OUT, initial=0)
                            rpiLogger.info(f"{self.name}::: GPIO IRLport configured (BCM {self.IRLport})")
                        else:
                            self.IRLport = None
                            rpiLogger.warning(f"{self.name}::: GPIO IRLport is not used")  

                        if self._config['use_pir'] == 1:
                            self.PIRport = self._config['bcm_pirport']
                            self.pirTimeDelta = timedelta(seconds=self._config['pirtd_sec'])
                            GPIO.setup(self.PIRport, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
                            # The bouncetime is set to avoid quick signal level changes
                            # The larger and configurable detection delay is added in _pirRun
                            self.lastPirDetected = datetime.now()
                            GPIO.add_event_detect(self.PIRport, GPIO.RISING, callback=self._pirRun, bouncetime=500)
                            rpiLogger.info(f"{self.name}::: GPIO PIRport configured (BCM {self.PIRport}, {self.pirTimeDelta}sec intv.)")  
                        else:
                            self.PIRport = None
                            rpiLogger.warning(f"{self.name}::: GPIO PIRport is not used")  

                    else:
                        GPIO.cleanup()
                        rpiLogger.error(f"{self.name}::: GPIO.getmode() returned None!")   
                        raise rpiBaseClassError(f"{self.name}::: GPIO.getmode() returned None!", ERRCRIT)
                    
                except RuntimeError as e:
                    rpiLogger.error(f"{self.name}::: GPIO could not be configured! {e}")   
                    raise rpiBaseClassError(f"{self.name}::: GPIO could not be configured! {e}", ERRCRIT)

            else:
                rpiLogger.warning(f"{self.name}::: GPIO is not used")   

        ### Reset flag indicating that PIR sensor has detected movement since last picture has been captured
        self.pirDetected.clear()

        ### Configuration for the image capture
        self._camera         = None
        self.camid           = self._config['image_id']
        self.exif_tags_copyr = 'Copyright (c) 2025 Istvan Z. Kovacs - All rights reserved'
        self.resolution      = (1024, 768)
        self.jpgqual         = 85
        self.rotation        = self._config['image_rot']
        # Init the font to use in the overlay text
        if RPICAM or RPICAM2:
            self._TXTfont = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)

        ### Init the "dark" time flag and reference image brightness
        # (used only when RPICAM or RASPISTILL= True)
        self.bDarkExp = False
        self.imgbr = 128

        ### Init the camera object
        if RPICAM2:
            # Picamera2 API, recommended since 2022!
            tuning = Picamera2.load_tuning_file(f"{LIBCAMERA_JSON:s}")
            self._camera = Picamera2(tuning=tuning)

            _still_config = self._camera.create_still_configuration()
            _still_config['main']['size'] = self.resolution

            # Set camera image rotation
            # Note: libcamera Transform does not support +/-90 degree rotation, so we apply it later with the PIL image (CCW)
            if self.rotation in [90, -270]:
                _orientation = 6
            elif self.rotation in [-90, 270]:
                _orientation = 8
            elif self.rotation == 180:
                _orientation = 3
                _still_config["transform"] = Transform(hflip=1, vflip=1)
            else:
                _orientation = 1

            self._camera.configure(_still_config)
            self._camera.options["quality"] = self.jpgqual

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
                            piexif.ImageIFD.Software: "rpicampy/v6",
                            piexif.ImageIFD.DateTime: time.strftime('%Y:%m:%d %H:%M:%S', time.localtime()),
                            piexif.ImageIFD.Artist: self.camid,
                            piexif.ImageIFD.ImageDescription: "Time-lapse with Rasberry Pi controlled (pi)camera",
                            piexif.ImageIFD.Copyright: self.exif_tags_copyr, 
                            piexif.ImageIFD.Orientation: _orientation,
                            piexif.ImageIFD.XResolution: (self.resolution[0],1),
                            piexif.ImageIFD.YResolution: (self.resolution[1],1),
                        },
                'Exif': {
                            piexif.ExifIFD.DateTimeOriginal: time.strftime('%Y:%m:%d %H:%M:%S', time.localtime()),
                        }
                }
            
        elif RPICAM:
            # Picamera API, depracated since 2022!
            self._camera = picamera.PiCamera()
            self._camera.resolution = self.resolution

            # Set camera image rotation
            if self.rotation == 180:
                self._camera.hflip = True
                self._camera.vflip = True
            self._camera.rotation = self.rotation

            # Set custom EXIF/TIFF tags
            self._camera.exif_tags['IFD0.Make'] = "Raspberry Pi"
            self._camera.exif_tags['IFD0.Software'] = "rpicampy"
            self._camera.exif_tags['IFD0.DateTime'] = time.strftime('%Y:%m:%d %H:%M:%S', time.localtime())
            self._camera.exif_tags['IFD0.Artist'] = self.camid
            self._camera.exif_tags['IFD0.ImageDescription'] = "Time-lapse with Rasberry Pi controlled (pi)camera"
            self._camera.exif_tags['IFD0.Copyright'] = self.exif_tags_copyr
            self._camera.exif_tags['IFD0.Orientation'] = _orientation
            self._camera.exif_tags['IFD0.XResolution'] = (self.resolution[0],1)
            self._camera.exif_tags['IFD0.YResolution'] = (self.resolution[1],1)

        ### Create output folder
        try:
            os.mkdir(self._config['image_dir'])
            self.imgSubDir = time.strftime('%d%m%y', time.localtime())
            rpiLogger.info(f"{self.name}::: Local output folder {self._config['image_dir']} created.")
        except OSError as e:
            if e.errno == EEXIST:
                rpiLogger.info(f"{self.name}::: Local output folder {self._config['image_dir']} already exist!" )
                pass
            else:
                raise rpiBaseClassError(f"{self.name}::: initClass(): Local output folder {self._config['image_dir']} could not be created!" , ERRCRIT)

        ### Fill in the fifo buffer with images found in the output directory
        ### Only the image files with the current date are listed!
        #imagelist_ref = sorted(glob.glob(self._config['image_dir'] + '/' + time.strftime('%d%m%y', time.localtime()) + '-*.jpg'))
        #self.imageFIFO.acquireSemaphore()
        #for img in imagelist_ref:
        #   if not img in self.imageFIFO:
        #       self.imageFIFO.append(img)
        #self.imageFIFO.releaseSemaphore()

        # Ephem parameters
        # The ephem.localtime() function converts a PyEphem date into a Python datetime object
        # expressed in your local time zone.
        # A negative value of horizon can be used when an observer is high off of the ground.
        self._sun = ephem.Sun()
        self._loc = ephem.Observer()
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



    def _pirRun(self,c):
        """
        Set the flag indicating that PIR sensor has detected movement since last picture has been captured
        Mark a new detection only after a configurable delay from the last detection
        """
        tnow = datetime.now()
        if tnow - self.lastPirDetected >= self.pirTimeDelta:
            self.pirDetected.set()
            self.lastPirDetected = tnow
            rpiLogger.info(f"{self.name}::: PIR flag set")
        else:
            rpiLogger.debug(f"{self.name}::: PIR flag NOT set")
        

    def _setCamExp(self):
        '''
        Set camera exposure according to the 'dark' time threshold.
        Used only with LIBCAMERA or RPICAM/RPICAM2
        '''
        if LIBCAMERA:
            # See Apendix C in Picamera2 API documentation.

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
            self.bDarkExp = False

            # The 'dark' mode settings
            if self._isDark():
                self.bDarkExp = True
                if self._config['use_irl'] == 1:
                    self.gain       = 4.0
                    self.contrast   = 1.5 
                    self.brightness = 20/50  
                else:
                    self.gain       = 8.0
                    self.contrast   = 1.3
                    self.brightness = 20/50                    
                    #self.framerate = Fraction(1, 2)
                    self.shutter_speed = 5000000

            # Set the list with the parameter values
            self.camexp_list = [
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
                self.camexp_list.extend([
                    "--shutter", f"{self.shutter_speed}"
                ])


        elif RPICAM2:
            # See Apendix C in Picamera2 API documentation. 

            # The 'daylight' default settings
            self._camera.set_controls( # pyright: ignore[reportOptionalMemberAccess]
            {
                "AeEnable": True,
                "AeExposureMode": controls.AeExposureModeEnum.Normal,
                "AwbEnable": True, 
                "AwbMode": controls.AwbModeEnum.Auto,
                "Contrast": 1.0, # Floating point number from 0.0 to 32.0
                "Brightness": 0.0, # Floating point number from -1.0 to 1.0
            })
            self.bDarkExp = False

            # The 'dark' mode settings
            if self._isDark():
                self.bDarkExp = True
                if self._config['use_irl'] == 1:
                    self._camera.set_controls( # pyright: ignore[reportOptionalMemberAccess]
                    {
                        "AeEnable": True,
                        "AeExposureMode": controls.AeExposureModeEnum.Long,
                        "Contrast": 5.0, # Floating point number from 0.0 to 32.0
                        "Brightness": 0.3, # Floating point number from -1.0 to 1.0
                        "AnalogueGain": 4.0,
                    })
                else:
                    self._camera.set_controls( # pyright: ignore[reportOptionalMemberAccess]
                    {
                        "AeEnable": True,
                        "AeExposureMode": controls.AeExposureModeEnum.Normal,
                        "ExposureTime": 300000, #usec
                        "Contrast": 5.0, # Floating point number from 0.0 to 32.0
                        "Brightness": 0.4, # Floating point number from -1.0 to 1.0
                        "AnalogueGain": 8.0,
                    })
  
        elif RPICAM:
            # Note: V1 API is deprecated since 2022!
            # https://picamera.readthedocs.io/en/release-1.13/api_camera.html
            # The 'daylight' default settings
            self._camera.awb_mode = 'auto'
            self._camera.iso = 0
            self._camera.contrast = 30
            self._camera.brightness = 50
            self._camera.exposure_mode = 'auto'
            time.sleep(2)
            self.bDarkExp = False
        
            # The 'dark' mode settings
            if self._isDark():
                self.bDarkExp = True
                if self._config['use_irl'] == 1:
                    self._camera.awb_mode = 'auto'
                    self._camera.iso = 0
                    self._camera.contrast = 50 #-100 ... 0 ... 100
                    self._camera.brightness = 70 #0 ... 50 ... 100
                    self._camera.exposure_mode = 'auto'
                    time.sleep(2)
                else:
                    self._camera.awb_mode = 'auto'
                    self._camera.iso = 800
                    self._camera.contrast = 30
                    self._camera.brightness = 70
                    #self._camera.framerate = Fraction(1, 2)
                    self._camera.exposure_mode = 'off'
                    #self._camera.meter_mode = 'spot'
                    self._camera.shutter_speed = 5000000
                    time.sleep(5)
                
    

    def _isDark(self):
        '''
        Determine if current time is in the "dark" period.
        '''

        # Check the current time against the (auto or manual) 'dark' time period
        if (self._config['start_dark_hour'] < 0 ) or (self._config['stop_dark_hour'] < 0):
            self._loc.date = datetime.now(timezone.utc)
            self._tdark_start = self._loc.previous_setting(self._sun)
            self._tdark_stop = self._loc.previous_rising(self._sun)

            if (self._tdark_start > self._tdark_stop):
                return True
            else:
                return False
        else:
            self._tlocal = time.localtime()
            self._tdark_start = time.mktime((self._tlocal.tm_year, self._tlocal.tm_mon, self._tlocal.tm_mday,
                        self._config['start_dark_hour'], self._config['start_dark_min'], 0,
                        self._tlocal.tm_wday, self._tlocal.tm_yday, self._tlocal.tm_isdst ))
            self._tdark_stop = time.mktime((self._tlocal.tm_year, self._tlocal.tm_mon, self._tlocal.tm_mday,
                        self._config['stop_dark_hour'], self._config['stop_dark_min'], 0,
                        self._tlocal.tm_wday, self._tlocal.tm_yday, self._tlocal.tm_isdst ))

            if (time.time() >= self._tdark_start) or (time.time() <= self._tdark_stop):
                return True
            else:
                return False


    def _switchIR(self, bONOFF):
        '''
        Switch ON/OFF the IR lights
        '''
        if self._config['use_irl'] == 1:
            if bONOFF:
                GPIO.output(self.IRLport,GPIO.HIGH)
            else:
                GPIO.output(self.IRLport,GPIO.LOW)

    ### The following 4 functions are based on:
    # https://github.com/andrevenancio/brightnessaverage
    # by Andre Venancio, June 2014
    # The calculated brightness value can be used to adjust the camera shutter speed:
    # ss = ss*(2 - self.imgbr/128)

    def _grayscaleAverage(self, image):
        '''
        Convert image to greyscale, return average pixel brightness.
        '''
        if self._config['use_irl'] == 0:
            # Upper-right ~1/3 image is masked out (black), not used in the statistics
            mask = Image.new('1', (image.size[0], image.size[1]))
            draw = ImageDraw.Draw(mask,'1')
            draw.rectangle([0,354,image.size[0],image.size[1]],fill=255)
            #draw.rectangle([0,0,410,356],fill=255)
            del draw

            stat = ImageStat.Stat(image.convert('L'), mask=mask)

        else:
            stat = ImageStat.Stat(image.convert('L'))

        self.imgbr = stat.mean[0]


    def _grayscaleRMS(self, image):
        '''
        Convert image to greyscale, return RMS pixel brightness.
        '''
        stat = ImageStat.Stat(image.convert('L'))
        self.imgbr = stat.rms[0]

    def _averagePerceived(self, image):
        '''
        Average pixels, then transform to "perceived brightness".
        '''
        if self._config['use_irl'] == 0:
            # Upper-right ~1/3 image is masked out (black), not used in the statistics
            mask = Image.new('1', (image.size[0], image.size[1]))
            draw = ImageDraw.Draw(mask,'1')
            draw.rectangle([0,354,image.size[0],image.size[1]],fill=255)
            #draw.rectangle([0,0,410,356],fill=255)
            del draw

            stat = ImageStat.Stat(image, mask=mask)

        else:
            stat = ImageStat.Stat(image)

        r,g,b = stat.mean
        self.imgbr = math.sqrt(0.241*(r**2) + 0.691*(g**2) + 0.068*(b**2))

    def _rmsPerceivedBrightness(self, image):
        '''
        RMS of pixels, then transform to "perceived brightness".
        '''
        stat = ImageStat.Stat(image)
        r,g,b = stat.rms
        self.imgbr = math.sqrt(0.241*(r**2) + 0.691*(g**2) + 0.068*(b**2))


#   def cvcamimg(self, output_file='test.jpg'):
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
