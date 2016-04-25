# -*- coding: utf-8 -*-
"""
    Time-lapse with Rasberry Pi controlled camera - VER 4.5 for Python 3.4+
    Copyright (C) 2016 Istvan Z. Kovacs

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
from datetime import datetime
import subprocess
import logging
import ephem

import rpififo
from rpibase import rpiBaseClass, rpiBaseClassError
from rpibase import ERRCRIT, ERRLEV2, ERRLEV1, ERRLEV0, ERRNONE

# OpenCV
#import numpy as np
##from scipy.misc import imread
#import cv2

# PILlow
from PIL import Image, ImageDraw, ImageFont, ImageStat
import math

#import unittest

### Camera input to use
# If not RPICAM and not RPISTILL then use a web camera with fswebcam utility
FAKESNAP   = False
RASPISTILL = False
RPICAM     = True

if FAKESNAP:
	# Dummy (no image capture!)
	RASPISTILL = False
	RPICAM     = False

if RPICAM:
	# PIcamera
	import picamera
	from fractions import Fraction
	import io

### Check for root/sudo (needed for GPIO)
if (os.getenv("SUDO_USER") == None) and (os.geteuid() != 0):
	USEGPIO = False
else:
	USEGPIO = True

if RPICAM or RASPISTILL:
	if USEGPIO:
		import RPi.GPIO as GPIO
		# Since 0.6.0a3: uses /dev/gpiomem if available to avoid being run as root? Not working in 0.6.2!
	else:
		logging.warning("The RPi.GPIO module is not used!")

class rpiCamClass(rpiBaseClass):
	"""
	Implements the rpiCam class, to run and control:
	- Raspberry PI camera using the raspistill utility or
	- Raspberry PI camera usingthe picamera module, or
	- Web camera using fswebcam utility.
	Use GPIO to ON/OFF control an IR/VL reflector for night imaging.
	"""

	def __init__(self, name, rpi_apscheduler, rpi_events, rpi_config, dbuff_rpififo=None):

		### Get the Dbx error event
		self._eventDbErr 	= rpi_events.eventErrList["DBXJob"]

		### Get the custom config parameters
		self._config = rpi_config

		### The FIFO buffer (deque)
		self.imageFIFO = rpififo.rpiFIFOClass([], self._config['list_size'])

		### Init base class
		super().__init__(name, rpi_apscheduler, rpi_events)

	def __repr__(self):
		return "<%s (name=%s, rpi_apscheduler=%s, rpi_events=dict(), rpi_config=%s, dbuff_rpififo=%s)>" % (self.__class__.__name__, self.name, self._sched, self._config, self.imageFIFO)

	def __str__(self):
		msg = super().__str__()
		return "%s::: %s, config: %s, FAKESNAP: %s, RASPISTILL: %s, RPiCAM: %s\nimageFIFO: %s\n%s" % \
			(self.name, self.camid, self._config, FAKESNAP, RASPISTILL, RPICAM, self.imageFIFO, msg)

	def __del__(self):

		try:
			### Close the picamera
			if RPICAM:
				self._camera.close()

			### Clean up GPIO on exit
			if RPICAM or RASPISTILL:
				#GPIO.cleanup()
				self._switchIR(False)
		except:
			pass

		### Clean base class
		super().__del__()


	#
	# Main interface methods
	#

	def jobRun(self):

		### Create the daily output sub-folder
		### Set the full image file path
		#self._config['image_subdir'] = time.strftime('%d%m%y', time.localtime())
		self.imageFIFO.crtSubDir = time.strftime('%d%m%y', time.localtime())
		self._locdir = os.path.join(self._config['image_dir'], self.imageFIFO.crtSubDir)
		try:
			os.mkdir(self._locdir)
			logging.info("%s::: Local daily output folder %s created." % (self.name, self._locdir))

		except OSError as e:
			if e.errno == EEXIST:
				logging.debug("%s::: Local daily output folder %s already exist!" % (self.name, self._locdir))
				pass
			else:
				raise rpiBaseClassError("%s::: jobRun(): Local daily output folder %s could not be created" % (self.name, self._locdir) , ERRCRIT)

		finally:
			self.image_name = self.imageFIFO.crtSubDir + '-' + time.strftime('%H%M%S', time.localtime()) + '-' + self.camid + '.jpg'
			self.image_path = os.path.join(self._locdir, self.image_name)


		### Take a new snapshot and save the image locally
		try:
			# Lock the buffer
			self.imageFIFO.acquireSemaphore()

			if FAKESNAP:
				logging.debug('Faking snapshot: ' + self.image_name)
				self._grab_cam = subprocess.Popen("touch " + self.image_path, stderr=subprocess.PIPE, stdout=subprocess.PIPE, shell=True)

				# Check return/errors
				self._camoutput, self._camerrors = self._grab_cam.communicate()

			elif RASPISTILL:
				# Use raspistill -n -vf -hf -awb auto -q 95
				self._grab_cam = subprocess.Popen("raspistill -n -vf -hf -q 95 -co 30 -w 640 -h 480 -o " + self.image_path, stderr=subprocess.PIPE, stdout=subprocess.PIPE, shell=True)

				# Check return/errors
				#self.grab_cam.wait()
				self._camoutput, self._camerrors = self._grab_cam.communicate()

			elif RPICAM:
				# Init the camera
				#with picamera.PiCamera() as self._camera:
				self._camera = picamera.PiCamera()
				self._camera.resolution = (1024, 768)
				self._camera.exif_tags['IFD0.Copyright'] = 'Copyright (c) 2016 Istvan Z. Kovacs'
				#self._camera.hflip = True
				#self._camera.vflip = True
				self._camera.rotation = 0
				if self.camid == 'CAM1':
					self._camera.rotation = 90
				elif self.camid == 'CAM2':
					self._camera.rotation = 180


				# Set camera exposure according to the 'dark' time threshold
				self._setCamExp()

				# Create the in-memory stream
				stream = io.BytesIO()

				# Camera warm-up time and capture
				self._camera.capture(stream, format='jpeg')

				# Read stream to a PIL image
				stream.seek(0)
				image = Image.open(stream)

				# When in 'dark' time
				# Calculate brightness and adjust shutter speed
				sN = ': '
				if self.bDarkExp:
					sN = 'n' + sN

					if self.camid == 'CAM1':

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
							logging.debug('Before: Br=%d, Ss=%dus' % (self.imgbr, ss))

							# Re-capture the picture
							time.sleep(3)
							self._camera.shutter_speed = int(ss*(2 - float(self.imgbr)/128))
							self._camera.capture(stream, format='jpeg')
							stream.seek(0)
							image = Image.open(stream)

							# Re-calculate brightness
							self._averagePerceived(image)
							logging.debug('After: Br=%d, Ss=%dus' % (self.imgbr, self._camera.shutter_speed))

							# Lock the buffer
							self.imageFIFO.acquireSemaphore()

					#elif self.camid == 'CAM2':
						# Do nothing ?

					#else:
						# Do nothing ?


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
				# Use fswebcam -d /dev/video0 -s brightness=50% -s gain=32
				self._grab_cam = subprocess.Popen("fswebcam -d /dev/video0 -q -r 640x480 --jpeg=95 " + self.image_path, stderr=subprocess.PIPE, stdout=subprocess.PIPE, shell=True)

				### Check return/errors
				self._camoutput, self._camerrors = self._grab_cam.communicate()


			logging.info('Snapshot: ' + self.image_name)

			### Add image to deque (FIFO)
			self.imageFIFO.append(self.image_path)
			self.crtlenFIFO = len(self.imageFIFO)

			if self.crtlenFIFO > 0:
				logging.debug("imageFIFO[0..%d]: %s .. %s" % (self.crtlenFIFO-1, self.imageFIFO[0], self.imageFIFO[-1]))
			else:
				logging.debug("imageFIFO[]: empty")

			### Update status
			self.statusUpdate = (self.name, self.crtlenFIFO)

			### Close the picamera
			if RPICAM:
				self._camera.close()

		except OSError as e:
			raise rpiBaseClassError("%s::: jobRun(): Snapshot %s could not be created!\n%s" % (self.name, self.image_path, e), ERRLEV2)

		finally:
			# Release the buffer
			self.imageFIFO.releaseSemaphore()


	def initClass(self):
		""""
		(re)Initialize the class.
		"""

		### Host/cam ID
		self._camera = None
		self.camid = 'CAM1'
		if subprocess.check_output(["hostname", ""], shell=True).strip().decode('utf-8').find('pi2') > 0:
			self.camid = 'CAM2'

		### Init the FIFO buffer
		self.imageFIFO.camID = self.camid
		self.imageFIFO.clear()
		self.crtlenFIFO = 0

		### Init the "dark" time flag and reference image brightness
		# (used only when RPICAM or RASPISTILL= True)
		self.bDarkExp = False
		self.imgbr = 128

		### Init GPIO ports
		self.IRport = 19 # use GPIO19
		if USEGPIO:
			GPIO.cleanup(self.IRport)
			GPIO.setmode(GPIO.BCM)
			GPIO.setup(self.IRport, GPIO.OUT, initial=0)

		### Init the font
		self._TXTfont = ImageFont.truetype("/usr/share/fonts/truetype/freefont/FreeSans.ttf", 16)

		### Create output folder
		try:
			os.mkdir(self._config['image_dir'])
			self.imgSubDir = time.strftime('%d%m%y', time.localtime())
			logging.info("%s::: Local output folder %s created." % (self.name, self._config['image_dir']))
		except OSError as e:
			if e.errno == EEXIST:
				logging.info("%s::: Local output folder %s already exist!" % (self.name, self._config['image_dir']))
				pass
			else:
				raise rpiBaseClassError("%s::: initClass(): Local output folder %s could not be created" % (self.name, self._config['image_dir']) , ERRCRIT)

		### Fill in the fifo buffer with images found in the output directory
		### Only the image files with the current date are listed!
		#imagelist_ref = sorted(glob.glob(self._config['image_dir'] + '/' + time.strftime('%d%m%y', time.localtime()) + '-*.jpg'))
		#self.imageFIFO.acquireSemaphore()
		#for img in imagelist_ref:
		#	if not img in self.imageFIFO:
		#		self.imageFIFO.append(img)
		#self.imageFIFO.releaseSemaphore()

		# Ephem parameters
		# The ephem.localtime() function converts a PyEphem date into a Python datetime object 
		# expressed in your local time zone.
		self._sun = ephem.Sun()
		self._aal = ephem.Observer()
		self._aal.lat = '57.0774992'
		self._aal.lon = '9.9117876'
		self._aal.pressure = 0

#	def endDayOAM(self):
#		"""
#		End-of-Day OAM procedure.
#		"""

#	def endOAM(self):
#		"""
#		End OAM procedure.
#		"""


	# Camera control

	def _setCamExp(self):
		'''
		Set camera exposure according to the 'dark' time threshold.
		Used only when RPICAM or RASPISTILL = True.
		'''

		if RPICAM:
		
			# Set the "dark" exposure parameters when needed
			if self._isDark():
			
				if self.camid == 'CAM1':
					self._camera.awb_mode = 'auto'
					self._camera.iso = 800
					self._camera.contrast = 30
					self._camera.brightness = 70
					self._camera.framerate = Fraction(1, 2)
					self._camera.exposure_mode = 'off'
					#self._camera.meter_mode = 'spot'
					self._camera.shutter_speed = 5000000
					time.sleep(5)

				elif self.camid == 'CAM2':
				 	# Switch ON IR
					self._switchIR(True)

					self._camera.awb_mode = 'auto'
					self._camera.iso = 0
					self._camera.contrast = 50
					self._camera.brightness = 70
					self._camera.exposure_mode = 'auto'
					time.sleep(2)

				#else:
					# Do nothing

				self.bDarkExp = True

			else:

				if self.camid == 'CAM1':
					self._camera.awb_mode = 'auto'
					self._camera.iso = 0
					self._camera.contrast = 30
					self._camera.brightness = 50
					self._camera.exposure_mode = 'auto'
					time.sleep(2)

				elif self.camid == 'CAM2':
				 	# Switch OFF IR
					self._switchIR(False)

					self._camera.awb_mode = 'auto'
					self._camera.iso = 0
					self._camera.contrast = 30
					self._camera.brightness = 50
					self._camera.exposure_mode = 'auto'
					time.sleep(2)

				#else:
					# Do nothing

				self.bDarkExp = False

		#elif RASPISTILL:
			# TODO!

	def _isDark(self):
		'''
		Determine if current time is in the "dark" period.
		'''

		# Check the current time against the (auto or manual) 'dark' time period 
		if (self._config['dark_hours'][0] == 0) and (self._config['dark_hours'][1] == 0):
			self._tdark_start = self._aal.previous_setting(self._sun)
			self._tdark_stop = self._aal.previous_rising(self._sun)
		
			if (self._tdark_start > self._tdark_stop):
				return True
			else:
				return False	
		else:
			self._tlocal = time.time()
			self._tdark_start = time.mktime((self._tlocal.tm_year, self._tlocal.tm_mon, self._tlocal.tm_mday,
						self._config['dark_hours'][0], self._config['dark_mins'][0], 0,
						self._tlocal.tm_wday, self._tlocal.tm_yday, self._tlocal.tm_isdst ))
			self._tdark_stop = time.mktime((self._tlocal.tm_year, self._tlocal.tm_mon, self._tlocal.tm_mday,
						self._config['dark_hours'][1], self._config['dark_mins'][1], 0,
						self._tlocal.tm_wday, self._tlocal.tm_yday, self._tlocal.tm_isdst ))

			if (self._tlocal >= self._tdark_start) or (self._tlocal <= self._tdark_stop):
				return True
			else:
				return False		
		
	
	def _switchIR(self, bONOFF):
		'''
		Switch ON/OFF the IR lights
		'''
		if USEGPIO:
			if bONOFF:
				GPIO.output(self.IRport,1)
			else:
				GPIO.output(self.IRport,0)

	### The following 4 functions are based on:
	# https://github.com/andrevenancio/brightnessaverage
	# by Andre Venancio, June 2014
	# The calculated brightness value can be used to adjust the camera shutter speed:
	# ss = ss*(2 - self.imgbr/128)

	def _grayscaleAverage(self, image):
		'''
		Convert image to greyscale, return average pixel brightness.
		'''
		if self.camid == 'CAM1':
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
		if self.camid == 'CAM1':
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


#	def cvcamimg(self, output_file='test.jpg'):
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
