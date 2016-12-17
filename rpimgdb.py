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

Implements the rpiImageDbx class to manage images in a remote directory (dropbox).
Use Dropbox SDK, API V2, Python 3.4
https://www.dropbox.com/developers/documentation/python
https://github.com/dropbox/dropbox-sdk-python
"""

import os
import sys
import time
import datetime
import posixpath
import logging
import atexit

from dropbox import Dropbox
from dropbox.files import WriteMode, SearchMode, FileMetadata, FolderMetadata
from dropbox.exceptions import ApiError, AuthError, DropboxException, InternalServerError
from requests import exceptions
import json

# if six.PY3:
#     from io import StringIO
# else:
#     from StringIO import StringIO

import rpififo
from rpibase import rpiBaseClass, rpiBaseClassError
from rpibase import ERRCRIT, ERRLEV2, ERRLEV1, ERRLEV0, ERRNONE

class rpiImageDbxClass(rpiBaseClass):
	"""
	Implements the rpiImageDb class to manage images in a remote directory (dropbox).
	"""

	def __init__(self, name, rpi_apscheduler, rpi_events, rpi_config, cam_rpififo=None):

		### Get the Dbx error event
		#self._eventDbErr 	= rpi_events.eventErrList["DBXJob"]

		### Get the custom config parameters
		self._config = rpi_config

		### Get FIFO buffer for images from the camera (deque)
		self._imageFIFO = cam_rpififo

		### The FIFO buffer for the uploaded images (deque)
		self.imageUpldFIFO = rpififo.rpiFIFOClass([], 576)
		self.imageUpldFIFO.crtSubDir = ''

		### Init base class
		super().__init__(name, rpi_apscheduler, rpi_events)

	def __repr__(self):
		return "<%s (name=%s, rpi_apscheduler=%s, rpi_events=dict(), rpi_config=%s, dbuff_rpififo=%s)>" % (self.__class__.__name__, self.name, self._sched, self._config, self._imageFIFO)

	def __str__(self):
		msg = super().__str__()
		return "%s::: dbinfo: %s, config: %s\nimageUpldFIFO: %s\n%s" % \
				(self.name, self.dbinfo, self._config, self.imageUpldFIFO, msg)

	def __del__(self):
		### Clean base class
		super().__del__()



	#
	# Main interface methods
	#

	def jobRun(self):

		try:
			# Lock the buffer
			self._imageFIFO.acquireSemaphore()

			# Get the current images in the FIFO
			# Refresh the last remote image when available
			if len(self._imageFIFO):

				# Update remote cam image with the current (last) image
				if not (self._imageFIFO[-1] == self.crt_image_snap):
					self._putImage(self._imageFIFO[-1], self._config['image_snap'], True)
					self.crt_image_snap = self._imageFIFO[-1]
					self.numImgUpdDb += 1
					logging.info("Updated remote %s with %s" % (self._config['image_snap'], self._imageFIFO[-1]) )


				# Lock the upload buffer
				self.imageUpldFIFO.acquireSemaphore()

				# Check if a new upload sub-folder has to be used
				if not (self.imageUpldFIFO.crtSubDir == self._imageFIFO.crtSubDir):
					self.imageUpldFIFO.crtSubDir = self._imageFIFO.crtSubDir
					self.upldir = os.path.normpath(os.path.join(self._config['image_dir'], self.imageUpldFIFO.crtSubDir))
					self._mkdirImage(self.upldir)

				# Upload only images in the FIFO which have not been uploaded yet
				for img in self._imageFIFO:
					if not img in self.imageUpldFIFO:
						self._putImage(img, os.path.join(self.upldir, os.path.basename(img)))
						logging.info("Uploaded %s" % img )

				# Release the upload buffer
				self.imageUpldFIFO.releaseSemaphore()

				# Update status
				self.statusUpdate = (self.name, self.numImgUpdDb)

			else:
				# Update status
				self.statusUpdate = (self.name, ERRNONE)

				logging.info('Nothing to upload')


		# Handle exceptions, mostly HTTP/SSL related!
		except exceptions.Timeout as e:
			# Catching this error will catch both ReadTimeout and ConnectTimeout.
			raise rpiBaseClassError("%s::: jobRun(): Connect/ReadTimeoutError:\n%s" % (self.name, str(e)), ERRLEV2)

		except exceptions.ConnectionError as e:
			# A Connection error occurred.
			raise rpiBaseClassError("%s::: jobRun(): ConnectionError:\n%s" % (self.name, str(e)), ERRLEV2)

		except exceptions.HTTPError as e:
			# An HTTP error occurred.
			raise rpiBaseClassError("%s::: jobRun(): HTTPError:\n%s" % (self.name, str(e)), ERRLEV2)

		except exceptions.RequestException as e:
			# There was an ambiguous exception that occurred while handling your request.
			raise rpiBaseClassError("%s::: jobRun(): RequestException:\n%s" % (self.name, str(e)), ERRLEV2)

# 			except BadStatusLine as e:
# 				self.eventErr_set('run()')
# 				logging.debug("BadStatusLine:\n%s" % str(e))
# 				pass

		except rpiBaseClassError as e:
			if e.errval == ERRCRIT:
				self.endDayOAM()
			raise rpiBaseClassError("%s::: jobRun(): %s" % (self.name, e.errmsg), e.errval)

		except RuntimeError as e:
			self.endDayOAM()
			raise rpiBaseClassError("%s::: jobRun(): RuntimeError:\n%s" % (self.name, str(e)), ERRCRIT)

		except:
			self.endDayOAM()
			raise rpiBaseClassError("%s::: jobRun(): Unhandled Exception:\n%s" % (self.name, str(sys.exc_info())), ERRCRIT)

		finally:
			# Release the buffer
			self._imageFIFO.releaseSemaphore()


	def initClass(self):
		""""
		(re)Initialize the class.
		"""

		#self.imageDbHash = None
		self._imageDbCursor = None
		self.imageDbList = []
		self.numImgUpdDb = 0

		self.crt_image_snap = None
		self.imgid = self._imageFIFO.camID + '.jpg'
		self.upldir = os.path.normpath(os.path.join(self._config['image_dir'], self.imageUpldFIFO.crtSubDir))
		self.logfile = './upldlog.json'

		### When there are already images listed in the upload log file, then
		# make sure we don't upload them to the remote folder again
		# Else, create the file with an empty list; to be updated in endDayOAM()
		try:
			self.imageUpldFIFO.acquireSemaphore()
			self.imageUpldFIFO.clear()

			if os.path.isfile(self.logfile):
				with open(self.logfile,'r') as logf:
					upldimg = json.load(logf)

				for img in upldimg:
					self.imageUpldFIFO.append(img)

				del upldimg

				logging.info("%s::: Local log file %s found and loaded." % (self.name, self.logfile))
			else:
				with open(self.logfile,'w') as logf:
					json.dump([], logf)
					logging.info("%s::: Local log file %s initialized." % (self.name, self.logfile))

		except IOError:
			raise rpiBaseClassError("%s::: initClass(): Local log file %s was not found or could not be created." % (self.name, self.logfile), ERRCRIT)

		finally:
			# Release the upload buffer
			self.imageUpldFIFO.releaseSemaphore()

		### Init Dropbox API client
		self._token_file = self._config['token_file']
		self._dbx = None
		self.dbinfo = None
		try:
			with open(self._token_file, 'r') as token:
				self._dbx = Dropbox(token.read())

			info = self._dbx.users_get_current_account()
			# info._all_field_names_ =
			# {'account_id', 'is_paired', 'locale', 'email', 'name', 'team', 'country', 'account_type', 'referral_link'}
			self.dbinfo ={'email': info.email, 'referral_link': info.referral_link}

			logging.info("%s::: Loaded access token from ''%s''" % (self.name, self._token_file) )

			### Create remote root folder (relative to app root) if it does not exist yet
			self._mkdirImage(os.path.normpath(self._config['image_dir']))

		except rpiBaseClassError as e:
			if e.errval == ERRCRIT:
				self.endDayOAM()
			raise rpiBaseClassError("initClass(): %s" % e.errmsg, e.errval)

		except IOError:
			self.endDayOAM()
			raise rpiBaseClassError("initClass(): Token file ''%s'' could not be read." % (self.name, self._token_file), ERRCRIT)

		except AuthError as e:
			self.endDayOAM()
			raise rpiBaseClassError("initClass(): AuthError:\n%s" % e.error, ERRCRIT)

		except DropboxException as e:
			self.endDayOAM()
			raise rpiBaseClassError("initClass(): DropboxException:\n%s" %  str(e), ERRCRIT)

		except InternalServerError as e:
			self.endDayOAM()
			raise rpiBaseClassError("initClass(): InternalServerError:\n%s" % str(e.status_code),  ERRCRIT)


	def endDayOAM(self):
		"""
		End-of-Day Operation and Maintenance sequence.
		"""

		self._lsImage(self.upldir)
		logging.info("%s::: %d images in the remote folder %s" % (self.name, len(self.imageDbList), self.upldir))

		# Lock the uplaod buffer
		self.imageUpldFIFO.acquireSemaphore()

		try:
			upldimg=[]
			for img in self.imageUpldFIFO:
				upldimg.append(img)

			with open(self.logfile,'w') as logf:
				json.dump(upldimg, logf)

			del upldimg

			logging.info("%s::: Local log file %s updated." % (self.name, self.logfile))

		except IOError:
			raise rpiBaseClassError("endDayOAM(): Local log file %s was not found." % self.logfile,  ERRCRIT)

		finally:
			# Release the upload buffer
			self.imageUpldFIFO.releaseSemaphore()

#	def endOAM(self):
#		"""
#		End OAM procedure.
#		"""
	@atexit.register
	def atexitend():
		self.endDayOAM()

	def _lsImage(self,from_path):
		"""
		List the image/video files in the remote directory.
		Stores the found file names in self.imageDbList.
		"""
		try:
			if self._imageDbCursor is None:
				self.ls_ref = self._dbx.files_list_folder('/' + os.path.normpath(from_path), recursive=False, include_media_info=True )
			else:
				new_ls = self._dbx.files_list_folder_continue(self._imageDbCursor)
				if new_ls.entries == []:
					logging.debug("%s::: _lsImage():: No changes on the server." % self.name)
				else:
					self.ls_ref = new_ls

			# Select only images and only the ones for the current imgid (camid)
			foundImg = False
			for f in self.ls_ref.entries:
				if 'media_info' in f._all_field_names_ and \
					f.media_info is not None:
					if self.imgid in f.path_lower:
						img = '.%s' % f.path_lower
						foundImg = True
						if not img in self.imageDbList:
							self.imageDbList.append(img)


			if not foundImg:
				self.imageDbList = []

			### Store the hash of the folder
			self._imageDbCursor = self.ls_ref.cursor

			if len(self.imageDbList) > 0:
				logging.debug("%s::: _lsImage():: imageDbList[0..%d]: %s .. %s" % (self.name, len(self.imageDbList)-1, self.imageDbList[0], self.imageDbList[-1]) )
			else:
				logging.debug("%s::: _lsImage():: imageDbList[]: empty" % self.name)

		except ApiError as e:
			raise rpiBaseClassError("_lsImage(): %s" % e.error, ERRLEV2)


	def _putImage(self, from_path, to_path, overwrite=False):
		"""
		Copy local file to remote file.
		Stores the uploaded files names in self.imageUpldFIFO.

		Examples:
		_putImage('./path/test.jpg', '/path/dropbox-upload-test.jpg')
		"""
		mode = (WriteMode.overwrite if overwrite else WriteMode.add)

		with open(from_path, "rb") as from_file:
			try:
				self._dbx.files_upload( from_file.read(), '/' + os.path.normpath(to_path), mode)

				if not overwrite:
					self.imageUpldFIFO.append(from_path)

				logging.debug("%s::: _putImage(): Uploaded file from %s to remote %s" % (self.name, from_path, to_path))

			except ApiError as e:
				# This checks for the specific error where a user doesn't have
				# enough Dropbox space quota to upload this file
				if (err.error.is_path() and err.error.get_path().error.is_insufficient_space()):
					raise rpiBaseClassError("_putImage(): ERROR: Cannot back up; insufficient space.", ERRCRIT)
				elif err.user_message_text:
					raise rpiBaseClassError("_putImage(): %s" % e.user_message_text, ERRLEV2)
				else:
					raise rpiBaseClassError("_putImage(): %s" % e.error, ERRLEV2)

			#except IOError:
				#raise rpiBaseClassError("_putImage(): Local img file %s could not be opened." %  from_path, ERRCRIT)

	def _mkdirImage(self, path):
		"""
		Create a new remote directory.

		Examples:
		_mkdirImage('/dropbox_dir_test')
		"""
		try:
			self._dbx.files_create_folder('/' + os.path.normpath(path))

			logging.debug("%s::: Remote output folder /%s created." % (self.name, path))

		except ApiError as e:
			noerr = False
			# dropbox.files.CreateFolderError
			if e.error.is_path():
				# dropbox.files.WriteError
				we = e.error.get_path()
				if we.is_conflict():
					# dropbox.files.WriteConflictError
					wce = we.get_conflict()
					# union tag is 'folder'
					if wce.is_folder():
						logging.info("%s::: Remote output folder /%s already exist!" % (self.name, path))
						noerr = True

			if not noerr:
				raise rpiBaseClassError("_mkdirImage(): Remote output folder /%s was not created! %s" % (path, e.error), ERRCRIT)
			else:
				pass


	def _mvImage(self, from_path, to_path):
		"""
		Move/rename a remote file or directory.

		Examples:
		_mvImage('./path1/dropbox-move-test.jpg', '/path2/dropbox-move-test.jpg')
		"""
		try:
			self._dbx.files_move( '/' + os.path.normpath(from_path), '/' +  os.path.normpath(to_path) )

			logging.debug("%s::: _mvImage(): Moved file from %s to %s" % (self.name, from_path, to_path))

		except ApiError as e:
			raise rpiBaseClassError("_mvImage(): Image %s could not be moved to %s! %s" % (from_path, to_path, e.error), ERRLEV2)


# 	def _getImage(self, from_file, to_path):
# 		"""
# 		Copy file from remote directory to local file.
#
# 		Examples:
# 		_getImage('./path/dropbox-download-test.jpg', './file.jpg',)
# 		"""
# 		try:
# 			metadata, response  = self._dbx.files_download_to_file( to_path, '/' + os.path.normpath(from_file) )
# 			logging.debug("%s::: _getImage(): Downloaded file from remote %s to %s. Metadata: %s" % (self.name, from_file, to_path, metadata) )
#
# 		except ApiError as e:
# 			raise rpiBaseClassError("_getImage(): %s" % e.error, ERRLEV2)


# 	def _searchImage(self, string):
# 		"""
# 		Search remote directory for image/video filenames containing the given string.
# 		"""
# 		try:
# 			results = self._dbx.files_search( '', string, start=0, max_results=100, mode=SearchMode('filename', None) )
#
# 		except ApiError as e: #rest.ErrorResponse as e:
# 			raise rpiBaseClassError("_searchImage(): %s" % e.error, ERRLEV2)


# 	def _rmImage(self, path):
# 		"""
# 		Delete a remote image/video file
# 		"""
#
