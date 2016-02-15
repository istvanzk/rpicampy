# -*- coding: utf-8 -*-
"""
    Time-lapse with Rasberry Pi controlled camera - VER 4.0 for Python 3.4+
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

from rpibase import rpiBaseClass, rpiBaseClassError

class rpiImageDirClass(rpiBaseClass):
	"""
	Implements the rpiImageDir class to manage the set of saved images by rpiCam
	"""

	def __init__(self, deque_img, *args, **kwargs):
	
		### Get FIFO buffer (deque)							
		self._imageFIFO = deque_img
		
		### Get the Dbx error event	
		self._eventDbErr 	= args[2].eventErrList["DBXJob"] 
		
		### Init base class
		super(rpiImageDirClass,self).__init__(*args, **kwargs)
						
	def __str__(self):
		msg = super(rpiImageDirClass,self).__str__()	
		return "%s:::locdir: %s, image_names: %s, len(imagelist_ref): %d\n%s" % \
				(self.name, self._locdir, self._image_names, len(self._imagelist_ref), msg)

	def __del__(self):
		### Clean base class
		super(rpiImageDirClass,self).__del__()


	#
	# Main interface methods
	#		
	
	def jobRun(self):
				
								
		### List all jpg files in the current local sub-folder
		self._locdir = os.path.join(self._config['image_dir'], self._imageFIFO.crtSubDir)
		self._image_names = os.path.join(self._locdir, self._imageFIFO.crtSubDir + '-*.jpg')
		self.imagelist = sorted(glob.glob(self._image_names))
		if len(self.imagelist) > 0:
			logging.debug("imagelist: %s .. %s" % (self.imagelist[0], self.imagelist[-1]))
		else:
			logging.debug("imagelist: empty. No %s found!" % self._image_names)
		
		### Run directory/file management only if no errors were detected when 
		### updating to remote directory
		if not self._eventDbErr.is_set():
			### Process the new list only if it is changed and has at least max length
			if ( not (self._imagelist_ref == self.imagelist) ) and \
				len(self.imagelist) > self._config['list_size']:
	
				### Remove all the images not in the imageFIFO
				self._imageFIFO.acquireSemaphore()
		
				for img in self.imagelist:
					if not img in self._imageFIFO:					
						logging.info("Remove image: %s" % img)				
						self._rmimg = subprocess.Popen("rm " + img, stderr=subprocess.PIPE, stdout=subprocess.PIPE, shell=True) 
						self._diroutput, self._direrrors = self._rmimg.communicate()
			
						### Check return/errors
						if len(self._direrrors):	
							raise rpiBaseClassError("%s::: jobRun(): File could not be deleted! %s\n%s" % (self.name, self._camoutput, self._camerrors ), 3)
		
				self._imageFIFO.releaseSemaphore()
			
				#raise Exception('Test exception')	
				
			### Update REST feed
			self.restUpdate(len(self.imagelist))
		
			### Update image list in the current local sub-folder
			self._imagelist_ref = sorted(glob.glob(self._image_names))
			if len(self._imagelist_ref) > 0:
				logging.debug("imagelist_ref: %s .. %s" % (self._imagelist_ref[0], self.imagelist[-1]))
			else:
				logging.debug("imagelist_ref: empty. No %s found!" % self._image_names)
		
				
		else:
			logging.info("eventDbErr is set!")							



	def initClass(self):
		""""
		(re)Initialize the class
		"""

		### Init reference img file list
		self._locdir = os.path.join(self._config['image_dir'], self._imageFIFO.crtSubDir)
		self._image_names = os.path.join(self._locdir, self._imageFIFO.crtSubDir + '-*.jpg')		
		self._imagelist_ref = sorted(glob.glob(self._image_names))

		
#	def endDayOAM(self):
#		"""
#		End-of-Day 0AM
#		"""	
		
#	def endOAM(self):
#		"""
#		End OAM procedure.
#		"""	
