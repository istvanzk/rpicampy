# -*- coding: utf-8 -*-
"""
    Time-lapse with Rasberry Pi controlled camera - VER 3.1 for Python 3.4+
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
import datetime
import subprocess
import logging
import thingspk
import rpififo

# OpenCV
#import numpy as np
##from scipy.misc import imread 
#import cv2

# PILlow
from PIL import Image, ImageDraw, ImageFont, ImageStat
import math

#import unittest

# Camera input to use
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
	
if RPICAM or RASPISTILL:	
	import RPi.GPIO as GPIO

# if not RPICAM and not RPISTILL then use a web camera and fswebcam 

class rpiCamClass(object):
	"""
	Implements the rpiCam class, to run and control:
	- Raspberry PI camera using the raspistill utility or 
	- Raspberry PI camera usingthe picamera module, or
	- Web camera using fswebcam utility.
	Use GPIO to ON/OFF control an IR/VL reflector for night imaging.
	"""
		
	def __init__(self, name, dict_config, rpi_events, restapi=None):
	
		self.name 	= name
		self.config = dict_config
		
		self.eventDayEnd 	= rpi_events.eventDayEnd				
		self.eventEnd 		= rpi_events.eventEnd
		self.eventErr 		= rpi_events.eventErrList[self.name]
		self.eventErrcount 	= rpi_events.eventErrcountList[self.name]
		self.eventErrtime 	= rpi_events.eventErrtimeList[self.name]
		self.eventErrdelay	= rpi_events.eventErrdelayList[self.name]
		
		self.restapi = restapi

		### Init configs
		self.config['jobid'] = self.name
		self.config['run']   = True
		self.config['stop']  = False
		self.config['pause'] = False
		self.config['init']  = False
		self.config['cmdval'] = 3
		self.config['errval'] = 0
				
		### Make FIFO buffer (deque)					
		self.imageFIFO = rpififo.rpiFIFOClass([], self.config['list_size'])
						
		### Init class
		self.initClass()
												
	def __str__(self):
		return "%s::: %s, config:%s\nimageFIFO:%s\nFake snap:%s\neventErrdelay:%s" % \
			(self.name, self.camid, self.config, self.imageFIFO, FAKESNAP, self.eventErrdelay)
		
	def __del__(self):
		logging.debug("%s::: Deleted!" % self.name)

		### Close the picamera
		if RPICAM:
			self.camera.close()
			
		### Clean up GPIO on exit	
		if RPICAM or RASPISTILL:		
			#GPIO.cleanup()
			switchIR(False)
			
		### Update REST feed
		self.rest_update(-1)

	#
	# Run (as a Job in APScheduler)
	#		
	def run(self):
	
		if self.eventEnd.is_set():
			logging.info("%s::: eventEnd is set!" % self.name)
			return
			
		if self.eventErr.is_set():	
		
			### Error was detected
			logging.info("%s::: eventErr is set!" % self.name)
		
			### Try to reset  and clear the self.eventErr
			# after 2x self.eventErrdelay of failed access/run attempts
			if (time.time() - self.eventErrtime) > self.eventErrdelay:
				self.eventErrcount += 1
				if self.eventErrcount > 3:
					self.config['errval'] = 3
					
				self.initClass()	
			else:	
				logging.debug("%s::: eventErr was set at %s!" % (self.name, time.ctime(self.eventErrtime)))

		

		if not self.config['stop']:
			logging.debug("%s::: Stoped." % self.name)
			return

		if not self.config['pause']:
			logging.debug("%s::: Paused." % self.name)
			return
			
		if self.config['init']:
			self.initClass()
			return
					
		
		### Create the daily output sub-folder
		### Set the full image file path
		#self.config['image_subdir'] = time.strftime('%d%m%y', time.localtime())
		self.imageFIFO.crtSubDir = time.strftime('%d%m%y', time.localtime())
		self.locdir = os.path.join(self.config['image_dir'], self.imageFIFO.crtSubDir)
		try:
			os.mkdir(self.locdir)
			logging.info("%s::: Local daily output folder %s created." % (self.name, self.locdir))
		
		except OSError as e:
			if e.errno == EEXIST:
				logging.debug("%s::: Local daily output folder %s already exist!" % (self.name, self.locdir))
				pass	
			else:
				logging.error("%s::: Local daily output folder %s could not be created!" % (self.name, self.locdir))
				self.eventErr_set('run()')
				self.rest_update(-3)				
				raise	
				
		finally:
			self.image_name = self.imageFIFO.crtSubDir + '-' + time.strftime('%H%M%S', time.localtime()) + '-' + self.camid + '.jpg'
			self.image_path = os.path.join(self.locdir, self.image_name) 
			


		### Take a new snapshot and save the image locally 	
		try:														
			if FAKESNAP:
				logging.debug('Faking snapshot: ' + self.image_name) 
				self.grab_cam = subprocess.Popen("touch " + self.image_path, stderr=subprocess.PIPE, stdout=subprocess.PIPE, shell=True) 			
				
				### Check return/errors				
				self.output, self.errors = self.grab_cam.communicate()
				
			else:	
				if RASPISTILL:
					# Use raspistill -n -vf -hf -awb auto -q 95
					self.grab_cam = subprocess.Popen("raspistill -n -vf -hf -q 95 -co 30 -w 640 -h 480 -o " + self.image_path, stderr=subprocess.PIPE, stdout=subprocess.PIPE, shell=True) 
					
					### Check return/errors				
					#self.grab_cam.wait()
					self.output, self.errors = self.grab_cam.communicate()
					
				elif RPICAM:
					### Init the camera
					self.TXTfont = ImageFont.truetype("/usr/share/fonts/truetype/freefont/FreeSans.ttf", 16)
	
					#with picamera.PiCamera() as self.camera:
					self.camera = picamera.PiCamera()
					self.camera.resolution = (1024, 768)
					self.camera.exif_tags['IFD0.Copyright'] = 'Copyright (c) 2016 Istvan Z. Kovacs'
					#self.camera.hflip = True
					#self.camera.vflip = True
					self.camera.rotation = 0
					if self.camid == 'CAM1':
						self.camera.rotation = 90

					### Set camera exposure according to the 'dark' time threshold
					self.setPICamExp()

					### Create the in-memory stream
					stream = io.BytesIO()
																	
					### Camera warm-up time and capture
					#self.camera.capture( self.image_path, format='jpeg' )
					self.camera.capture(stream, format='jpeg')
						
					### Read stream to a PIL image 
					stream.seek(0)
					image = Image.open(stream)
												
					### When in 'dark' time
					### Calculate brightness and adjust shutter speed
					sN = ': '
					if self.bDarkExp:
						sN = 'n' + sN

						if self.camid == 'CAM1':
						
							### Calculate brightness
							#self.grayscaleAverage(image)
							self.averagePerceived(image)
						
							### Recapture image with new shutter speed if needed
							if self.imgbr < 118 or \
								self.imgbr > 138:
							
								logging.info('IMGbr: %d' % self.imgbr)							
															
								ss = self.camera.shutter_speed

								logging.info('CAMss: %d' % ss)							

								self.camera.shutter_speed = int(ss*(2 - float(self.imgbr)/128))

								logging.info('CAMss: %d' % self.camera.shutter_speed)							
																
								time.sleep(2)
								self.camera.capture(stream, format='jpeg')
							
								stream.seek(0)
								image = Image.open(stream)
								
						#elif self.camid == 'CAM2':
							# Do nothing ?
									
						#else:
							# Do nothing ?
							
					
					### Add overlay text to the final image
					draw = ImageDraw.Draw(image,'RGBA')	
					draw.rectangle([0,image.size[1]-20,image.size[0],image.size[1]], fill=(150,200,150,100))
					draw.text((2,image.size[1]-18), self.camid + sN + time.strftime('%b %d %Y, %H:%M', time.localtime()), fill=(0,0,0,0), font=self.TXTfont)
					#n_width, n_height = TXTfont.getsize('#XX')
					#draw.text((image.size[0]-n_width-2,image.size[1]-18), '#XX', fill=(0,0,0,0), font=TXTfont)	
					del draw 
					
					### Save image and close
					image.save( self.image_path, format='jpeg', quality=95 )
					#image.close() 
					
					### Close BytesIO stream
					stream.close()
					
					### Set output indicators
					self.output = self.image_path
					self.errors = ''
					
				else:
					# Use fswebcam -d /dev/video0 -s brightness=50% -s gain=32
					self.grab_cam = subprocess.Popen("fswebcam -d /dev/video0 -q -r 640x480 --jpeg=95 " + self.image_path, stderr=subprocess.PIPE, stdout=subprocess.PIPE, shell=True) 
					
					### Check return/errors
					self.output, self.errors = self.grab_cam.communicate()
										
				
			self.imageFIFO.acquireSemaphore()
												
			if len(self.errors):	
				logging.error('Snapshot not available! Error: %s' % self.errors )
				
			else:
				### Add image to deque (FIFO)
				self.imageFIFO.append(self.image_path)
					
				logging.info('Snapshot: ' + self.image_name) 
					
			self.crtlenFIFO = len(self.imageFIFO)
			if self.crtlenFIFO > 0:
				logging.debug("imageFIFO[0..%d]: %s .. %s" % (self.crtlenFIFO-1, self.imageFIFO[0], self.imageFIFO[-1]))
			else:
				logging.debug("imageFIFO[]: empty")
			
			self.imageFIFO.releaseSemaphore()
			
			### Update REST feed
			self.rest_update(self.crtlenFIFO)
			
			
		except RuntimeError as e:
			self.eventErr_set('run()')
			self.rest_update(-3)
			logging.error("RuntimeError: %s! Exiting!" % str(e), exc_info=True)
			raise
					
		except:
			self.eventErr_set('run()')
			self.rest_update(-4)
			logging.error("Exception: %s! Exiting!" % str(sys.exc_info()), exc_info=True)
			raise
												
		finally:
		
			### Close the picamera
			if RPICAM:
				self.camera.close()
												
	
	### Helpers
	def eventErr_set(self,str_func):
		self.eventErr.set()
		self.eventErrtime = time.time()
		self.config['errval'] |= 1
		self.rest_update(-2)
		logging.debug("%s::: Set eventErr in %s at %s!" % (self.name, str_func, time.ctime(self.eventErrtime)))
	
	def eventErr_clear(self,str_func):
		if self.eventErr.is_set():
			self.eventErr.clear()
			self.eventErrtime = 0
			self.eventErrdelay = 120		
			err = self.config['errval']
			self.config['errval'] ^= 1
			self.rest_update(0)
			logging.debug("%s::: Clear eventErr in %s!" % (self.name, str_func))

	def initClass(self):
		""""
		(re)Initialize the class
		"""

		logging.info("%s::: Intialize class" % self.name) 
				
		### REST feed
		self.restapi_fieldid = 'field2'		
				
		### Init error event
		self.eventErr_clear("initClass()")

		### Host/cam ID
		self.camera = None
		self.camid = 'CAM1'
		if subprocess.check_output(["hostname", ""], shell=True).strip().decode('utf-8').find('pi2') > 0:
			self.camid = 'CAM2'
						
		### Init the FIFO buffer		
		self.imageFIFO.clear()		
		self.crtlenFIFO = 0

		### Init the "dark" time flag and reference image brightness 
		# (used only when RPICAM or RASPISTILL= True)		
		self.bDarkExp = False
		self.imgbr = 128						
					
		### Init GPIO ports
		self.IRport = 19 # use GPIO19
		GPIO.cleanup(self.IRport)
		GPIO.setmode(GPIO.BCM) 
		GPIO.setup(self.IRport, GPIO.OUT, initial=0)
										
		### Create output folder
		try:
			os.mkdir(self.config['image_dir'])
			self.imgSubDir = time.strftime('%d%m%y', time.localtime())
			logging.info("%s::: Local output folder %s created." % (self.name, self.config['image_dir']))
		except OSError as e:
			if e.errno == EEXIST:
				logging.info("%s::: Local output folder %s already exist!" % (self.name, self.config['image_dir']))
				pass
			else:
				logging.error("%s::: Local output folder %s could not be created!" % (self.name, self.config['image_dir']))
				self.eventErr_set('initClass()')
				self.rest_update(-3)			
				raise	
									
		### Fill in the fifo buffer with images found in the output directory	
		### Only the image files with the current date are listed!			
		#imagelist_ref = sorted(glob.glob(self.config['image_dir'] + '/' + time.strftime('%d%m%y', time.localtime()) + '-*.jpg'))		
		#self.imageFIFO.acquireSemaphore()
		#for img in imagelist_ref:
		#	if not img in self.imageFIFO:
		#		self.imageFIFO.append(img)
		#self.imageFIFO.releaseSemaphore()

		### Clear init flag			
		self.config['init'] = False
			
	def endDayOAM(self):
		"""
		End-of-Day OAM
		"""	
		
		logging.info("%s::: EoD maintenance sequence run" % self.name) 

		### Init class	
		self.initClass()																				

		if not self.eventErr.is_set():	
		
			self.eventDayEnd.clear()
			logging.debug("%s::: Reset eventEndDay" % self.name)

		else:
			logging.debug("%s::: eventErr is set" % self.name)	
	
	def rest_update(self, stream_value):
		"""
		REST API function to upload a value. 			
		"""
		if self.restapi is not None:
			self.restapi.setfield(self.restapi_fieldid, stream_value)
			if stream_value < 0:
				self.restapi.setfield('status', "%sError: %s" % (self.name, time.ctime(self.eventErrtime)))
									

	def setPICamExp(self):
		'''
		Set camera exposure according to the 'dark' time threshold.
		Used only when RPICAM or RASPISTILL = True.
		'''
		
		if RPICAM:
			# Set the current 'dark' time threshold
			self.tlocal = time.localtime()
			self.tdark_start = time.mktime((self.tlocal.tm_year, self.tlocal.tm_mon, self.tlocal.tm_mday, 
						self.config['dark_hours'][0], self.config['dark_mins'][0], 0,
						self.tlocal.tm_wday, self.tlocal.tm_yday, self.tlocal.tm_isdst ))	
			self.tdark_stop = time.mktime((self.tlocal.tm_year, self.tlocal.tm_mon, self.tlocal.tm_mday, 
						self.config['dark_hours'][1], self.config['dark_mins'][1], 0,
						self.tlocal.tm_wday, self.tlocal.tm_yday, self.tlocal.tm_isdst ))	

			# Set the "dark" exposure parameters when needed
			if (time.time() >= self.tdark_start) or (time.time() <= self.tdark_stop):
			
				if self.camid == 'CAM1': 
					self.camera.awb_mode = 'auto'
					self.camera.iso = 800
					self.camera.contrast = 30
					self.camera.brightness = 70
					self.camera.framerate = Fraction(1, 2)
					self.camera.exposure_mode = 'off'
					#self.camera.meter_mode = 'spot'					
					self.camera.shutter_speed = 5000000
					time.sleep(5)
				
				elif self.camid == 'CAM2':
				 	# Switch ON IR
					self.switchIR(True)
	
					self.camera.awb_mode = 'auto'
					self.camera.iso = 0
					self.camera.contrast = 50
					self.camera.brightness = 70
					self.camera.exposure_mode = 'auto'
					time.sleep(2)
				 					 	
				#else:
					# Do nothing
					 	
				self.bDarkExp = True
			
			else:

				if self.camid == 'CAM1': 			
					self.camera.awb_mode = 'auto'
					self.camera.iso = 0
					self.camera.contrast = 30
					self.camera.brightness = 50
					self.camera.exposure_mode = 'auto'
					time.sleep(2)

				elif self.camid == 'CAM2':
				 	# Switch OFF IR
					self.switchIR(False)

					self.camera.awb_mode = 'auto'
					self.camera.iso = 0
					self.camera.contrast = 30
					self.camera.brightness = 50
					self.camera.exposure_mode = 'auto'
					time.sleep(2)

				#else:
					# Do nothing

				self.bDarkExp = False
			
		#elif RASPISTILL:
			# TODO!
			
						
	### The following 4 functions are based on:
	# https://github.com/andrevenancio/brightnessaverage
	# by Andre Venancio, June 2014
	# The calculated brightness value can be used to adjust the camera shutter speed:
	# ss = ss*(2 - self.imgbr/128)
	
	def grayscaleAverage(self, image):
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
		
		
	def grayscaleRMS(self, image):
		'''
		Convert image to greyscale, return RMS pixel brightness.
		'''
		stat = ImageStat.Stat(image.convert('L'))
		self.imgbr = stat.rms[0]

	def averagePerceived(self, image):
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

	def rmsPerceivedBrightness(self, image):
		'''
		RMS of pixels, then transform to "perceived brightness".
		'''
		stat = ImageStat.Stat(image)
		r,g,b = stat.rms
		self.imgbr = math.sqrt(0.241*(r**2) + 0.691*(g**2) + 0.068*(b**2))


	def switchIR(self, bONOFF):
		'''
		Switch ON/OFF the IR lights
		'''
		if bONOFF:
			GPIO.output(self.IRport,1)
		else:
			GPIO.output(self.IRport,0)
					
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

					
	