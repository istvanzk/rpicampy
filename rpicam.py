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
from datetime import datetime, timezone
import subprocess
import ephem
import math

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
# See https://www.raspberrypi.com/documentation/accessories/camera.html
# LIBCAMERA is the preferred/recommended option since Debian Bullseye, Nov 2021
# LIBCAMERA_JSON has to be set to the JSON file name corresponding to the used camera (see docs above)
# RASPISTILL and RPICAM are deprecated since Debian Bullseye, Nov 2021
# RPICAM2 is not available, under development, Nov 2021
LIBCAMERA  = True
LIBCAMERA_JSON = "ov5647_noir.json" # Cam V1 Noir: dtoverlay=ov5647 in /boot/config.txt
#LIBCAMERA_JSON = "imx219.json" # Cam V2: dtoverlay=imx219 in /boot/config.txt
#RPICAM2    = False
RASPISTILL = False
RPICAM     = False


if FAKESNAP:
    # Dummy (no image capture!)
    LIBCAMERA  = False
    RPICAM2    = False
    RASPISTILL = False
    RPICAM     = False
    

if RPICAM:
    # PIcamera
    import picamera
    from fractions import Fraction
    import io
    # PILlow
    from PIL import Image, ImageDraw, ImageFont, ImageStat


#elif RPICAM2:
    # PIcamera2
    #import picamera2
    #from fractions import Fraction
    #import io

### GPIO
if not FAKESNAP:
    # Uses /dev/gpiomem if available to avoid being run as root
    # To enable user access too /dev/gpiomem run: sudo usermod -a -G gpio $USER
    import RPi.GPIO as GPIO
else:
    rpiLogger.warning("The RPi.GPIO module is not used!")

class rpiCamClass(rpiBaseClass):
    """
    Implements the rpiCam class, to run and control:
    - Raspberry PI camera using libcamera-still (new libcamera stack, preferred), or
    - Raspberry PI camera using the picamera python module, or
    - Raspberry PI camera using the raspistill utility, or 
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

        ### Init base class
        super().__init__(name, rpi_apscheduler, rpi_events)

        ### Configuration for the image capture
        self._camera         = None
        self.exif_tags_copyr = 'Copyright (c) 2022 Istvan Z. Kovacs'
        self.resolution      = (1024, 768)
        self.jpgqual         = 85
        self.rotation        = self._config['image_rot']
        self.camexp_list     = list()
        self.cmd_str         = list()

        ### Init GPIO ports, BCMxx pin. NO CHECK!
        self.pirDetected = False
        self.IRLport = None
        self.PIRport = None
        if not FAKESNAP:
            if self._config['use_irl'] == 1 or self._config['use_pir'] == 1:
                GPIO.setmode(GPIO.BCM)

                if GPIO.getmode() is not None: 

                    if self._config['use_irl'] == 1:
                        self.IRLport = self._config['bcm_irlport']
                        GPIO.setup(self.IRLport, GPIO.OUT, initial=0)
                    else:
                        self.IRLport = None
                        rpiLogger.warning(f"{self.name}::: GPIO IRLport not used")  

                    if self._config['use_pir'] == 1:
                        self.PIRport = self._config['bcm_pirport']
                        GPIO.setup(self.PIRport, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                        # The manualRun callback (see rpibase.py) triggers the execution of the job just as it would be executed by the scheduler
                        GPIO.add_event_detect(self.PIRport, GPIO.FALLING, callback=self.pirRun, bouncetime=15000)  
                    else:
                        self.PIRport = None
                        rpiLogger.warning(f"{self.name}::: GPIO PIRport not used")  

                else:
                    GPIO.cleanup()
                    rpiLogger.error(f"{self.name}::: GPIO could not be initialised!")   

            else:
                rpiLogger.warning(f"{self.name}::: No GPIO port is used")   


    def __repr__(self):
        return "<%s (name=%s, rpi_apscheduler=%s, rpi_events=dict(), rpi_config=%s, dbuff_rpififo=%s)>" % (self.__class__.__name__, self.name, self._sched, self._config, self.imageFIFO)

    def __str__(self):
        msg = super().__str__()
        return "%s::: %s, config: %s, FAKESNAP: %s, LIBCAMERA: %s, RASPISTILL: %s, RPiCAM: %s\nimageFIFO: %s\n%s" % \
            (self.name, self.camid, self._config, FAKESNAP, LIBCAMERA, RASPISTILL, RPICAM, self.imageFIFO, msg)

    def __del__(self):

        try:
            ### Close the picamera
            if RPICAM:
                self._camera.close()

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

        ### Clean base class
        super().__del__()


    #
    # Main interface methods
    #

    def pirRun(self,c):
        """
        Set flag indicating that PIR sensor has detected movement since last picture has been captured
        """
        self.pirDetected = True

    def jobRun(self):

        ### Check flag indicating that PIR sensor has detected movement since last picture has been captured
        if self._config['use_pir'] == 1:
            if self.pirDetected:
                rpiLogger.info(f"{self.name}::: PIR trigger detected")
                self.pirDetected = False
            else:
                rpiLogger.info(f"{self.name}::: PIR trigger NOT detected")
                return


        ### Create the daily output sub-folder
        ### Set the full image file path
        #self._config['image_subdir'] = time.strftime('%d%m%y', time.localtime())
        self.imageFIFO.crtSubDir = time.strftime('%d%m%y', time.localtime())
        self._locdir = os.path.join(self._config['image_dir'], self.imageFIFO.crtSubDir)
        try:
            os.mkdir(self._locdir)
            rpiLogger.info("%s::: Local daily output folder %s created." % (self.name, self._locdir))

        except OSError as e:
            if e.errno == EEXIST:
                rpiLogger.debug("%s::: Local daily output folder %s already exist!" % (self.name, self._locdir))
                pass
            else:
                raise rpiBaseClassError("%s::: jobRun(): Local daily output folder %s could not be created" % (self.name, self._locdir) , ERRCRIT)

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

            elif LIBCAMERA:
                # https://www.raspberrypi.com/documentation/accessories/camera.html#common-command-line-options

                # Set camera exposure according to the 'dark' time threshold
                self._setCamExp()

                # Generate the arguments
                self.cmd_str.extend([
                    "libcamera-still", "--tuning-file", f"/usr/share/libcamera/ipa/raspberrypi/{LIBCAMERA_JSON:s}", 
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
                self._camoutput, self._camerrors = self._grab_cam.communicate(timeout=8)

                #self._grab_cam = subprocess.run(self.cmd_str, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
                #self._camoutput, self._camerrors = self._grab_cam.stdout, self._grab_cam.stderr

                # TODO: post-process to add text with OpenCV
                # https://www.raspberrypi.com/documentation/accessories/camera.html#post-processing
                # https://www.raspberrypi.com/documentation/accessories/camera.html#writing-your-own-post-processing-stages


            #elif RPICAM2:


            elif RASPISTILL:
                # Deprecated!
                # https://www.arducam.com/docs/cameras-for-raspberry-pi/native-raspberry-pi-cameras/native-camera-commands-raspistillraspivid/
                # https://www.raspberrypi.com/documentation/accessories/camera.html#raspistill
                
                # Generate the arguments
                self.cmd_str.extend(["raspistill", 
                    "-n", 
                    "-rot", f"{self.rotation:n}",
                    "-q", f"{self.jpgqual:n}",
                    "-w", f"{self.resolution[0]}", "-h", f"{self.resolution[1]}", 
                    "-co", "30",
                    "-o", f"{self.image_path:s}"])

                # Capture image
                self._grab_cam = subprocess.Popen(self.cmd_str, stderr=subprocess.PIPE, stdout=subprocess.PIPE)

                # Check return/errors
                #self.grab_cam.wait()
                self._camoutput, self._camerrors = self._grab_cam.communicate()

            elif RPICAM:
                # Deprecated!
                # https://picamera.readthedocs.io/en/release-1.13/api_camera.html

                # Init the camera
                self._camera = picamera.PiCamera()
                self._camera.resolution = self.resolution
                self._camera.exif_tags['IFD0.Copyright'] = self.exif_tags_copyr
                #self._camera.hflip = True
                #self._camera.vflip = True
                self._camera.rotation = self.rotation

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
            raise rpiBaseClassError("%s::: jobRun(): Snapshot %s could not be created!\n%s" % (self.name, self.image_path, e), ERRLEV2)

        except subprocess.TimeoutExpired:
            self._grab_cam.kill()
            self._camoutput, self._camerrors = self._grab_cam.communicate()

        finally:

            ### Lock the buffer
            self.imageFIFO.acquireSemaphore()

            ### Check if the image file has been actually saved
            if os.path.exists(self.image_path):
                rpiLogger.info(f"Snapshot saved: {self.image_name:s}")

                # Add image to deque (FIFO)
                self.imageFIFO.append(self.image_path)
                self.crtlenFIFO = len(self.imageFIFO)

            else:
                rpiLogger.warning(f"Snapshot NOT saved: {self.image_name:s}!")
                rpiLogger.warning(f"List of args: {self.cmd_str}")
                rpiLogger.debug(f"Error was: {self._camerrors.decode()}")

            ### Info about the FIFO buffer
            if self.crtlenFIFO > 0:
                rpiLogger.debug("imageFIFO[0..%d]: %s .. %s" % (self.crtlenFIFO-1, self.imageFIFO[0], self.imageFIFO[-1]))
            else:
                rpiLogger.debug("imageFIFO[]: empty")

            ### Update status
            self.statusUpdate = (self.name, self.crtlenFIFO)

            ### Release the buffer
            self.imageFIFO.releaseSemaphore()

            ### Close the picamera
            if RPICAM:
                self._camera.close()

            ### Switch off IR
            self._switchIR(False)


    def initClass(self):
        """"
        (re)Initialize the class.
        """

        ### Cam ID
        self._camera = None
        self.camid = self._config['image_id']

        ### Init the FIFO buffer
        self.imageFIFO.camID = self.camid
        self.imageFIFO.clear()
        self.crtlenFIFO = 0

        ### Init the "dark" time flag and reference image brightness
        # (used only when RPICAM or RASPISTILL= True)
        self.bDarkExp = False
        self.imgbr = 128

        ### Reset flag indicating that PIR sensor has detected movement since last picture has been captured
        self.pirDetected = False

        ### Init the font
        if RPICAM:
            self._TXTfont = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)

        ### Create output folder
        try:
            os.mkdir(self._config['image_dir'])
            self.imgSubDir = time.strftime('%d%m%y', time.localtime())
            rpiLogger.info("%s::: Local output folder %s created." % (self.name, self._config['image_dir']))
        except OSError as e:
            if e.errno == EEXIST:
                rpiLogger.info("%s::: Local output folder %s already exist!" % (self.name, self._config['image_dir']))
                pass
            else:
                raise rpiBaseClassError("%s::: initClass(): Local output folder %s could not be created" % (self.name, self._config['image_dir']) , ERRCRIT)

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
        self._loc.lat = self._config['dark_loc'][0]
        self._loc.lon = self._config['dark_loc'][1]
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


    # Camera control

    def _setCamExp(self):
        '''
        Set camera exposure according to the 'dark' time threshold.
        Used only with LIBCAMERA or RPICAM
        '''
        if LIBCAMERA:
            # https://www.raspberrypi.com/documentation/accessories/camera.html#common-command-line-options
            # TODO: Test these settings
            self.shutter_speed = None
            self.awb_mode      = 'auto'
            self.exposure_mode = 'normal'
            self.gain       = 1.0 # ISO = 100 * analog gain (V1 camera)
            self.contrast   = 1.0 # 0 ... 1 ...    
            self.brightness = 0   #-1 ... 0 ... +1
            self.saturation = 1.0 # 0 ... 1 ...
            self.ev         = 0 # -10 ... 0 ... 10
            self.metering   = 'average'
            
            if self._isDark():
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

                self.bDarkExp = True

            else:
                self.contrast = 1.3

                self.bDarkExp = False

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


        elif RPICAM:
            # https://picamera.readthedocs.io/en/release-1.13/api_camera.html
            # Set the "dark" exposure parameters when needed
            if self._isDark():

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
                    self._camera.framerate = Fraction(1, 2)
                    self._camera.exposure_mode = 'off'
                    #self._camera.meter_mode = 'spot'
                    self._camera.shutter_speed = 5000000
                    time.sleep(5)

                self.bDarkExp = True

            else:

                self._camera.awb_mode = 'auto'
                self._camera.iso = 0
                self._camera.contrast = 30
                self._camera.brightness = 50
                self._camera.exposure_mode = 'auto'
                time.sleep(2)

                self.bDarkExp = False


    def _isDark(self):
        '''
        Determine if current time is in the "dark" period.
        '''

        # Check the current time against the (auto or manual) 'dark' time period
        if (self._config['dark_hours'][0] == 0) and (self._config['dark_hours'][1] == 0):
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
                        self._config['dark_hours'][0], self._config['dark_mins'][0], 0,
                        self._tlocal.tm_wday, self._tlocal.tm_yday, self._tlocal.tm_isdst ))
            self._tdark_stop = time.mktime((self._tlocal.tm_year, self._tlocal.tm_mon, self._tlocal.tm_mday,
                        self._config['dark_hours'][1], self._config['dark_mins'][1], 0,
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
