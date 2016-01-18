# -*- coding: utf-8 -*-
"""
    Time-lapse with Rasberry Pi controlled camera - VER 3.0 for Python 3.4+
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
    
Implements the rpiImageDb class to manage images in a remote directory (dropbox).    
Use Dropbox SDK, API V2, Python 3.4
https://www.dropbox.com/developers/documentation/python
https://github.com/dropbox/dropbox-sdk-python
"""

import os
import sys
import six
import time
import datetime
import posixpath
from http.client import BadStatusLine
from ssl import SSLError
from queue import Queue
import logging

if six.PY3:
    from io import StringIO
else:
    from StringIO import StringIO

from dropbox import Dropbox
from dropbox.files import WriteMode, SearchMode, FileMetadata, FolderMetadata
from dropbox.exceptions import ApiError, AuthError, DropboxException, InternalServerError

from urllib3 import exceptions

import thingspk
import rpififo
import json

class rpiImageDbClass():
	"""
	Implements the rpiImageDb class to manage images in a remote directory (dropbox).
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
		
		self.restapi = restapi 
		
		self.imgSubDir = rpififo.imgSubDir
				
		### Init class
		self.initClass()
		
								                    			                    				
	def __str__(self):
		return "%s::: dbinfo:%s\nconfig:%s\nimageUpldList:%s\neventErrdelay:%s" % \
				(self.name, self.dbinfo, self.config, self.imageUpldList, self.eventErrdelay)
	
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

			### Try to reset DB API and clear the self.eventErr
			# after 2x self.eventErrdelay of failed access/run attempts
			if (time.time() - self.eventErrtime) > self.eventErrdelay:
				self.initClass()					
			else:	
				logging.debug("eventErr was set at %s!" % time.ctime(self.eventErrtime))

		else:			
		
			try:					
				### End-of-day OAM:
				# 1) List all files found in the remote upload sub-folder
				# 2) Dumps the list of all uploaded image files to the log file
				# 3) Init Dropbox API client
				if self.eventDayEnd.is_set():
					self.endDayOAM()
				
				else:
					
					### Init the remote upload sub-folder
					self.upldir = os.path.normpath(os.path.join(self.config['image_dir'], self.imgSubDir))
					self.mkdirImage(self.upldir)
					#self.lsImage(self.upldir)
								
					### Get the current images in the FIFO
					### Refresh the last remote image when available
					self.imageFIFO.acquireSemaphore()
					if len(self.imageFIFO): 
		
						### Update remote cam image with the current (last) image						
						if not (self.imageFIFO[-1] == self.crt_image_snap):
							self.putImage(self.imageFIFO[-1], self.config['image_snap'], True)
							self.crt_image_snap = self.imageFIFO[-1]
							self.numImgUpdDb += 1
							logging.info("Updated remote %s with %s" % (self.config['image_snap'], self.imageFIFO[-1]) )

						### Upload all images in the FIFO which have not been uploaded yet
						for img in self.imageFIFO:
							if img not in self.imageUpldList:
								self.putImage(img, os.path.join(self.upldir, os.path.basename(img)))
								logging.info("Uploaded %s" % img )

						### Update REST feed
						self.rest_update(self.numImgUpdDb)
																					
					else:
						### Update REST feed
						self.rest_update(0)
				
						logging.info('Nothing to upload')							

					self.imageFIFO.releaseSemaphore()
				
																			
			### Handle exceptions, mostly HTTP/SSL related!
			except BadStatusLine as e:
				self.eventErr_set('run()')
				logging.debug("BadStatusLine:\n%s" % str(e))
				pass

			except exceptions.SSLError as e:
				self.eventErr_set('run()')
				logging.debug("SSLError:\n%s" % str(e))
				pass
		
			except exceptions.TimeoutError as e:
				### Catching this error will catch both ReadTimeoutErrors and ConnectTimeoutErrors.
				self.eventErr_set('run()')
				logging.debug("Connect/ReadTimeoutError:\n%s" % str(e))
				pass
					
			except exceptions.MaxRetryError as e:
				self.eventErr_set('run()')
				logging.debug("MaxRetryError:\n%s" % str(e))
				pass
				
			except exceptions.ConnectionError as e:
				self.eventErr_set('run()')
				logging.debug("ConnectionError:\n%s" % str(e))
				pass
			
			except exceptions.ProtocolError as e:
				self.eventErr_set('run()')
				logging.debug("ProtocolError:\n%s" % str(e))
				pass
			
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
		(re)Initialize the class.
		"""
	
		logging.info("%s::: Intialize class" % self.name) 
		
		### Init error event
		self.eventErr.clear()
		self.eventErrtime  = 0
		self.eventErrdelay = 300
						
		#self.imageDbHash = None
		self.imageDbCursor = None
		self.imageDbList = [] 
		self.imageUpldList = []
		self.numImgUpdDb = 0
		
		self.current_path = '.'
		self.crt_image_snap = 'none'
		self.upldir = os.path.normpath(self.config['image_dir'])
		self.logfile = './upldlog.json'		
		
		### When there are already images listed in the upload log file, then
		# make sure we don't upload them to the remote folder again
		# Else, create the file with an empty list; to be updated in endDayOAM()
		try:
			if os.path.isfile(self.logfile):
				with open(self.logfile,'r') as logf:
					self.imageUpldList = json.load(logf)
					logging.info("%s::: Json log file ''%s'' found and loaded." % (self.name, self.logfile))
			else:
				with open(self.logfile,'w') as logf:
					json.dump([], logf)
					logging.info("%s::: Json log file ''%s'' initialized." % (self.name, self.logfile))
				
		except IOError:
			### Update REST feed
			self.rest_update(-5)
			logging.error("%s::: Local json log file ''%s'' was not found or could not be created! Exiting!" % (self.name, self.logfile), exc_info=True)
			raise
			
		### Init Dropbox API client		
		#self.app_key = self.config['app_key']
		#self.app_secret = self.config['app_secret']
		self.token_file = self.config['token_file']	
		self.dbx = None
		self.dbinfo = None
		try:
			with open(self.token_file, 'r') as token:
				self.dbx = Dropbox(token.read())
					
			info = self.dbx.users_get_current_account()
			# info._all_field_names_ = 
			# {'account_id', 'is_paired', 'locale', 'email', 'name', 'team', 'country', 'account_type', 'referral_link'}
			self.dbinfo ={'email': info.email, 'referral_link': info.referral_link}
			
			logging.info("%s::: Loaded access token from ''%s''" % (self.name, self.token_file) )
	
			### Create remote root folder (relative to app root) if it does not exist yet
			self.mkdirImage(os.path.normpath(self.config['image_dir']))
					
		except IOError:
			self.eventErr_set("initClass()")
			self.rest_update(-5)
			logging.error("%s::: Token file ''%s'' not found! Exiting!" % (self.name, self.token_file), exc_info=True)
			raise
		
		except AuthError as e:
			logging.error("%s::: AuthError:\n%s" % (self.name, str(e)))
			raise
				
		except DropboxException as e: 
			logging.error("%s::: DropboxException:\n%s" % (self.name, str(e)))
			raise
		
		except InternalServerError as e:	
			logging.error("%s::: InternalServerError:\n%s" % (self.name, str(e)))
			raise
		
		### Update REST feed
		self.restapi_fieldid = 'field3'		
		self.rest_update(0)
		

	def endDayOAM(self):
		"""
		End-of-Day Operation and Maintenance sequence.
		"""	
		
		logging.info("%s::: EoD maintenance sequence run" % self.name) 

		### List all files found in the remote sub-folder
		### Dumps the list of all uploaded image files to the log file
		if not self.eventErr.is_set():

			self.lsImage(self.upldir)		
			logging.info("%s::: %d images in the remote folder %s" % (self.name, len(self.imageDbList), self.upldir))

			try:
				with open(self.logfile,'w') as logf:
					json.dump(self.imageUpldList, logf)

			except IOError:
				self.eventErr_set("endDayOAM()")
				self.rest_update(-5)
				logging.error("%s::: Local log file ''%s'' could not be created! Exiting!" % (self.name, self.logfile), exc_info=True)
				raise

			self.eventDayEnd.clear()
			logging.debug("%s::: Reset eventEndDay" % self.name)
	
		else:
			logging.debug("%s::: eventErr is set" % self.name)	
			

		### Init class	
		self.initClass()																				
					
	
	def rest_update(self, stream_value):
		"""
		REST API function to upload a value. 			
		"""
		if self.restapi is not None:
			self.restapi.setfield(self.restapi_fieldid, stream_value)
			if stream_value < 0:
				self.restapi.setfield('status', "%sError: %s" % (self.name, time.ctime(self.eventErrtime)))			
				
	def lsImage(self,from_path):
		"""
		List the image/video files in the remote directory.
		Stores the found file names in self.imageDbList.	
		"""
		if not self.eventErr.is_set():
			try:
				if self.imageDbCursor is None:
					self.ls_ref = self.dbx.files_list_folder('/' + os.path.normpath(from_path), recursive=False, include_media_info=True )  
				else:
					new_ls = self.dbx.files_list_folder_continue(self.imageDbCursor)  
					if new_ls.entries == []:
						logging.debug("lsImage():: No changes on the server")				
					else:
						self.ls_ref = new_ls
				
				
				foundImg = False
				for f in self.ls_ref.entries:
					if 'media_info' in f._all_field_names_ and \
						f.media_info is not None:
						img = '.%s' % f.path_lower
						foundImg = True
						if not img in self.imageDbList:
							self.imageDbList.append(img)
			
				
				if not foundImg:
					self.imageDbList = []	
											
				### Store the hash of the folder
				#self.imageDbHash = self.ls_ref['hash']
				self.imageDbCursor = self.ls_ref.cursor
				
				if len(self.imageDbList) > 0:				
					logging.debug("lsImage():: imageDbList[0..%d]: %s .. %s" % (len(self.imageDbList)-1, self.imageDbList[0], self.imageDbList[-1]) )
				else:
					logging.debug("lsImage():: imageDbList[]: empty")
			
			except ApiError as e: 
				logging.debug("lsImage():: %s", e.user_message_text)
				pass 
				
		else:
			logging.debug("lsImage():: eventErr is set")	
	
	
	def putImage(self, from_path, to_path, overwrite=False):
		"""
		Copy local file to remote file.
		Stores the uploaded files names in self.imageUpldList.	

		Examples:
		putImage('./path/test.jpg', './path/dropbox-upload-test.jpg')
		"""
		if not self.eventErr.is_set():		
			try:
				mode = (WriteMode.overwrite if overwrite else WriteMode.add)
            
				with open(from_path, "rb") as from_file:
					#self.api_client.put_file(to_path, from_file, overwrite)
					self.dbx.files_upload( from_file, '/' + os.path.normpath(to_path), mode)
					
					if not overwrite:
						self.imageUpldList.append(from_path)
						#self.imageDbList.append(from_path)
						
					logging.debug("putImage():: Uploaded file from %s to remote %s" % (from_path, to_path))
			
			except ApiError as e: 
				logging.debug("putImage():: %s", e.user_message_text)
				pass 
				
#			except RateLimitError as e:

# 			except IOError:
# 				### Update REST feed
# 				self.rest_update(-3)
# 				
# 				logging.error("putImage():: IOError: %s! Exiting!" % str(sys.exc_info()), exc_info=True)
# 				#sys.exit(3)	
# 				raise DBThreadExitError(3, 	'putImage():: IOError')		

			
		else:
			logging.debug("putImage():: eventErr is set")	
			

	def mkdirImage(self, path):
		"""
		Create a new remote directory.
		
		Examples:
		mkdirImage('./dropbox_dir_test')		
		"""
		if not self.eventErr.is_set():				
			try:
				self.dbx.files_create_folder('/' + os.path.normpath(path))

				logging.info("mkdirImage():: Remote output folder %s created." % path)
	
			except ApiError as e:
				logging.debug("mkdirImage():: Remote output folder %s was not created! %s" % (path, e)) #.user_message_text
				pass 
					
		else:
			logging.debug("mkdirImage():: eventErr is set")	
        
        
	def mvImage(self, from_path, to_path):
		"""
		Move/rename a remote file or directory.
	
		Examples:
		mvImage('./path1/dropbox-move-test.jpg', './path2/dropbox-move-test.jpg')		
		"""
		if not self.eventErr.is_set():		
			try:
				self.dbx.files_move( '/' + os.path.normpath(from_path), '/' +  os.path.normpath(to_path) )
				
				logging.debug("mvImage():: Moved file from %s to %s" % (from_path, to_path))
										
			except ApiError as e: 
				logging.debug("mvImage():: %s", e)
				pass 
			
		else:
			logging.debug("mvImage():: eventErr is set")	
	
# 	def getImage(self, from_file, to_path):
# 		"""
# 		Copy file from remote directory to local file.
# 
# 		Examples:
# 		getImage('./path/dropbox-download-test.jpg', './file.jpg',)
# 		"""
# 		if not self.eventErr.is_set():
# 			try:
# 				metadata, response  = self.dbx.files_download_to_file( to_path, '/' + os.path.normpath(from_file) )
# 				logging.debug("getImage():: Downloaded file from remote %s to %s. Metadata: %s" % (from_file, to_path, metadata) )
# 			
# 			except ApiError as e: 
# 				logging.debug("getImage():: %s", e.user_message_text)
# 				pass 
#
# 		else:
# 			logging.debug("getImage():: eventErr is set")	

	
# 	def searchImage(self, string):
# 		"""
# 		Search remote directory for image/video filenames containing the given string.
# 		"""
# 		if not self.eventErr.is_set():				
# 			try:
# 				results = self.dbx.files_search( '', string, start=0, max_results=100, mode=SearchMode('filename', None) )
# 				
# 			#for r in results.matches:
# 			#	print(r)
# 
# 			except ApiError as e: #rest.ErrorResponse as e:
# 				logging.debug("searchImage():: %s", e.user_message_text)
# 				pass
# 
# 		else:
# 			logging.debug("searchImage():: eventErr is set")	

	        
# 	def rmImage(self, path):
# 		"""
# 		Delete a remote image/video file 
# 		"""
# 		




