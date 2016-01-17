# -*- coding: utf-8 -*-
"""
    Time-lapse with Rasberry Pi controlled camera - VER 2.1 for Python 3.4+
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
    
Implements the rpiImageDir class to manage the set of saved images by rpiCam    
"""

import os
import sys
import glob
import time
import datetime
import subprocess
import logging
import thingspk

class rpiImageDirClass():
	"""
	Implements the rpiImageDir class to manage the set of saved images by rpiCam
	"""

	def __init__(self, name, dict_config, deque_img, rpi_events, restapi=None):
		
		self.name = name
		self.config = dict_config
		self.imageFIFO = deque_img
		
		self.eventDayEnd 	= rpi_events.eventDayEnd		
		self.eventEnd 		= rpi_events.eventEnd
		self.eventErr 		= rpi_events.eventErrList[self.name]
		self.eventErrtime 	= rpi_events.eventErrtimeList[self.name]
		self.eventErrdelay	= rpi_events.eventErrdelayList[self.name]
							
		self.eventDbErr 	= rpi_events.eventErrList['DBJob']
			
		self.imgSubDir      = rpi_events.imgSubDir
									
		self.restapi = restapi 
		
		### Init class
		self.initClass()
						
	def __str__(self):
		return "%s::: config:%s\nimagelist_ref:%s\neventErrdelay:%s" % \
			(self.name, self.config, self.imagelist_ref, self.eventErrdelay)

#	def __del__(self):
#		logging.debug("%s::: Deleted!" % self.name)

		### Update REST feed
#		self.rest_update(-1)

	#
	# Run (as a Job in APScheduler)
	#			
	def run(self):
	
		if self.eventEnd.is_set():

			### The end
			logging.info("%s::: eventEnd is set" % self.name)
		
		elif self.eventErr.is_set():	
		
			### Error was detected
			logging.info("%s::: eventErr is set" % self.name)

			### Try to reset  and clear the self.eventErr
			# after 2x self.eventErrdelay of failed access/run attempts
			if (time.time() - self.eventErrtime) > self.eventErrdelay:
				self.initClass()	
			else:	
				logging.debug("eventErr was set at %s!" % time.ctime(self.eventErrtime))

		else:			
		
			try:
				### End-of-day OAM
				# 1) ...
				if self.eventDayEnd.is_set():
					self.endDayOAM()
				
				else:
							
					### List all jpg files in the current local sub-folder
					self.locdir = os.path.join(self.config['image_dir'], self.imgSubDir)
					self.imagelist = sorted(glob.glob(self.locdir + '/' + self.imgSubDir + '-*.jpg'))
					if len(self.imagelist) > 0:
						logging.debug("imagelist: %s .. %s" % (self.imagelist[0], self.imagelist[-1]))
					else:
						logging.debug("imagelist: empty")
					
					### Run directory/file management only if no errors were detected when 
					### updating to remote directory
					if not self.eventDbErr.is_set():
						### Process the new list only if it is changed and has at least max length
						if ( not (self.imagelist_ref == self.imagelist) ) and \
							len(self.imagelist) > self.config['list_size']:
				
							### Remove all the images not in the imageFIFO
							self.imageFIFO.acquireSemaphore()
					
							for img in self.imagelist:
								if not img in self.imageFIFO:					
									logging.info("Remove image: %s" % img)				
									self.rmimg = subprocess.Popen("rm " + img, stderr=subprocess.PIPE, stdout=subprocess.PIPE, shell=True) 
									self.output, self.errors = self.rmimg.communicate()
						
									### Check return/errors
					
							self.imageFIFO.releaseSemaphore()
						
							#raise Exception('Test exception')	
							
						### Update REST feed
						self.rest_update(len(self.imagelist))
					
						### Update image list in the current local sub-folder
						self.imagelist_ref = sorted(glob.glob(self.locdir + '/' + self.imgSubDir + '-*.jpg'))
						if len(self.imagelist_ref) > 0:
							logging.debug("imagelist_ref: %s .. %s" % (self.imagelist_ref[0], self.imagelist[-1]))
						else:
							logging.debug("imagelist_ref: empty")
					
							
					else:
						logging.info("eventDbErr is set!")							


			### Handle exceptions
			except RuntimeError as e:
				self.eventErr_set('run()')
				self.rest_update(-3)
				logging.error("RuntimeError: %s! Exiting!" % str(e), exc_info=True)
				raise
						
			except:
				self.eventErr_set('run()')
				self.rest_update(-4)
				logging.error("Exception: %s! Exiting!" % str(sys.exc_info()), exc_info=True)
				pass										
						
									

	### Helpers
	def eventErr_set(self,str_func):
		self.eventErr.set()
		self.eventErrtime = time.time()
		self.rest_update(-2)
		logging.debug("%s::: Set eventErr in %s at %s!" % (self.name, str_func, time.ctime(self.eventErrtime)))

	
	def eventErr_clear(self,str_func):
		if self.eventErr.is_set():
			self.eventErr.clear()
			self.eventErrtime = 0
			self.rest_update(0)
			logging.debug("%s::: Clear eventErr in %s!" % (self.name, str_func))

	def initClass(self):
		""""
		(re)Initialize the class
		"""

		logging.info("%s::: Intialize class" % self.name)  

		### Init error event
		self.eventErr.clear()
		self.eventErrtime  = 0
		self.eventErrdelay = 120

		### Init reference img file list
		self.imagelist_ref = sorted(glob.glob(self.config['image_dir'] + '/' + time.strftime('%d%m%y', time.localtime()) + '-*.jpg'))

		### Update REST feed
		self.restapi_fieldid = 'field4'
		self.rest_update(0)

	def endDayOAM(self):
		"""
		End-of-Day 0AM
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
