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

Implements the rpiImageDbx class to manage images in a remote directory (dropbox).
Use Dropbox SDK, API V2, Python 3.9+
https://dropbox-sdk-python.readthedocs.io/en/latest/index.html
"""
import os
import sys
#import time
#import posixpath
#import atexit
import pickle
try:
    import json
except ImportError:
    import simplejson as json

try:
    from dropbox import Dropbox, DropboxOAuth2FlowNoRedirect
    from dropbox.files import WriteMode, SearchMode, FileMetadata, FolderMetadata
    from dropbox.exceptions import ApiError, AuthError, DropboxException, InternalServerError
    from requests import exceptions
    DBXUSE = True
except ImportError:
    DBXUSE = False
    pass

### The rpicampy modules
from rpilogger import rpiLogger
if not DBXUSE:
    rpiLogger.error("rpimgdb::: Dropbox module not found or not available!")
    os._exit(1)

import rpififo
from rpibase import rpiBaseClass, rpiBaseClassError
from rpibase import ERRCRIT, ERRLEV2, ERRLEV1, ERRLEV0, ERRNONE
from rpiconfig import RPICAMPY_VER

TOKEN_EXPIRATION_BUFFER = 300  # seconds

class rpiImageDbxClass(rpiBaseClass):
    """
    Implements the rpiImageDb class to manage images in a remote directory (dropbox).
    """

    def __init__(self, name, rpi_apscheduler, rpi_events, rpi_config, cam_rpififo):

        ### Init base class
        super().__init__(name, rpi_apscheduler, rpi_events, rpi_config)

        ### Get the Dbx error event
        #self._eventDbErr   = rpi_events.eventErrList["DBXJob"]

        ### Get FIFO buffer for images from the camera (deque)
        self._imageFIFO: rpififo.rpiFIFOClass = cam_rpififo

        ### The FIFO buffer for the uploaded images (deque)
        self.imageUpldFIFO = rpififo.rpiFIFOClass([], 576)
        self.imageUpldFIFO.crtSubDir = ''

        ### As last step, run automatically the initClass()
        self.initClass()

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
                    rpiLogger.info("rpimgdb::: Updated remote %s with %s", self._config['image_snap'], self._imageFIFO[-1] )


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
                        rpiLogger.info("rpimgdb::: Uploaded %s", img)

                # Release the upload buffer
                self.imageUpldFIFO.releaseSemaphore()

                # Update status
                self.statusUpdate = (self.name, self.numImgUpdDb)

            else:
                # Update status
                self.statusUpdate = (self.name, ERRNONE)

                rpiLogger.info('rpimgdb::: Nothing to upload.')


        # Handle exceptions, mostly HTTP/SSL related!
        except exceptions.Timeout as e:
            # Catching this error will catch both ReadTimeout and ConnectTimeout.
            rpiLogger.warning("rpimgdb::: jobRun(): Connect/ReadTimeoutError!\n%s", str(e))
            raise rpiBaseClassError("rpimgdb::: jobRun(): Connect/ReadTimeoutError!", ERRLEV2)

        except exceptions.ConnectionError as e:
            # A Connection error occurred.
            rpiLogger.warning("rpimgdb::: jobRun(): ConnectionError!\n%s", str(e))
            raise rpiBaseClassError("rpimgdb::: jobRun(): ConnectionError!", ERRLEV2)

        except exceptions.HTTPError as e:
            # An HTTP error occurred.
            rpiLogger.warning("rpimgdb::: jobRun(): HTTPError!\n%s", str(e))
            raise rpiBaseClassError("rpimgdb::: jobRun(): HTTPError!", ERRLEV2)

        except exceptions.RequestException as e:
            # There was an ambiguous exception that occurred while handling your request.
            rpiLogger.warning("rpimgdb::: jobRun(): RequestException!\n%s", str(e))
            raise rpiBaseClassError("rpimgdb::: jobRun(): RequestException!", ERRLEV2)

#           except BadStatusLine as e:
#               self.eventErr_set('run()')
#               rpiLogger.debug("rpimgdb::: BadStatusLine!")
#               pass

        except rpiBaseClassError as e:
            if e.errval == ERRCRIT:
                self.endDayOAM()
            rpiLogger.error("rpimgdb::: jobRun() BaseClassError!\n%s\n", str(e))
            raise rpiBaseClassError(f"rpimgdb::: jobRun() {str(e)}!", e.errval)

        except RuntimeError as e:
            self.endDayOAM()
            rpiLogger.error("rpimgdb::: jobRun(): RuntimeError!\n%s\n", str(e))
            raise rpiBaseClassError("rpimgdb::: jobRun(): RuntimeError!", ERRCRIT)

        except Exception as e:
            self.endDayOAM()
            rpiLogger.error("rpimgdb::: jobRun(): Unhandled Exception!\n%s\n", str(e))
            raise rpiBaseClassError("rpimgdb::: jobRun(): Unhandled Exception!", ERRCRIT)

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

                rpiLogger.info("rpimgdb::: initClass(): Local log file %s found and loaded.", self.logfile)
            else:
                with open(self.logfile,'w') as logf:
                    json.dump([], logf)
                    rpiLogger.info("rpimgdb::: initClass(): Local log file %s initialized.", self.logfile)

        except IOError:
            rpiLogger.error("rpimgdb::: initClass(): Local log file %s was not found or could not be created!\n%s\n", self.logfile, str(e))
            raise rpiBaseClassError(f"rpimgdb::: initClass(): Local log file {self.logfile} was not found or could not be created!", ERRCRIT)

        finally:
            # Release the upload buffer
            self.imageUpldFIFO.releaseSemaphore()

        ### Init Dropbox API client
        # See https://github.com/dropbox/dropbox-sdk-python/blob/main/example/oauth/commandline-oauth-scopes.py
        self._token_file = self._config['token_file']
        self._tokens = None
        self._dbx = None
        self.dbinfo = None
        try:
            #with open(self._token_file, 'r') as token:
            #    self._access_token = token.read().rstrip()
            # Read pkl file
            with open(self._token_file, 'rb') as f:
                self._tokens = pickle.load(f)

            # Initialize the client
            self._dbx = Dropbox(
                oauth2_access_token=self._tokens["oauth_result"].access_token,
                user_agent=RPICAMPY_VER,
                oauth2_access_token_expiration=self._tokens["oauth_result"].expires_at,
                oauth2_refresh_token=self._tokens["oauth_result"].refresh_token,
                app_key=self._tokens['app_key'],
                app_secret=self._tokens['app_secret']
            )

            info = self._dbx.users_get_current_account()
            # info._all_field_names_ =
            # {'account_id', 'is_paired', 'locale', 'email', 'name', 'team', 'country', 'account_type', 'referral_link'}
            self.dbinfo ={'email': info.email, 'referral_link': info.referral_link} # pyright: ignore[reportAttributeAccessIssue]

            rpiLogger.info("rpimgdb::: initClass(): Loaded access token from '%s'", self._token_file)

            ### Create remote root folder (relative to app root) if it does not exist yet
            self._mkdirImage(os.path.normpath(self._config['image_dir']))

        except rpiBaseClassError as e:
            if e.errval == ERRCRIT:
                self.endDayOAM()
            rpiLogger.error("rpimgdb::: initClass() BaseClassError!\n%s\n", str(e))
            raise rpiBaseClassError("rpimgdb::: initClass() %s!" % e, e.errval)

        except IOError as e:
            self.endDayOAM()
            rpiLogger.error("rpimgdb::: initClass(): Token file '%s' could not be read!\n%s\n", str(e))
            raise rpiBaseClassError(f"rpimgdb::: initClass(): Token file '{self._token_file}' could not be read!", ERRCRIT)

        except AuthError as e:
            self.endDayOAM()
            rpiLogger.error("rpimgdb::: initClass(): AuthError!\n%s\n", str(e))
            raise rpiBaseClassError("rpimgdb::: initClass(): AuthError!", ERRCRIT)

        except DropboxException as e:
            self.endDayOAM()
            rpiLogger.error("rpimgdb::: initClass(): DropboxException!\n%s\n", str(e))
            raise rpiBaseClassError("rpimgdb::: initClass(): DropboxException!", ERRCRIT)

        except InternalServerError as e:
            self.endDayOAM()
            rpiLogger.error("rpimgdb::: initClass(): InternalServerError!\n%s\n", str(e))
            raise rpiBaseClassError("rpimgdb::: initClass(): InternalServerError!", ERRCRIT)


    def endDayOAM(self):
        """
        End-of-Day Operation and Maintenance sequence.
        """

        self._lsImage(self.upldir)
        rpiLogger.info("rpimgdb:::  endDayOAM(): %d images in the remote folder %s", len(self.imageDbList), self.upldir)

        # Lock the uplaod buffer
        self.imageUpldFIFO.acquireSemaphore()

        try:
            upldimg=[]
            for img in self.imageUpldFIFO:
                upldimg.append(img)

            with open(self.logfile,'w') as logf:
                json.dump(upldimg, logf)

            del upldimg

            rpiLogger.info("rpimgdb::: endDayOAM(): Local log file %s updated.", self.logfile)

        except IOError as e:
            rpiLogger.error("rpimgdb::: endDayOAM(): Local log file %s was not found!\n%s\n", self.logfile, str(e))
            raise rpiBaseClassError(f"rpimgdb::: endDayOAM(): Local log file {self.logfile} was not found!",  ERRCRIT)

        finally:
            # Release the upload buffer
            self.imageUpldFIFO.releaseSemaphore()

#   def endOAM(self):
#       """
#       End OAM procedure.
#       """
#   @atexit.register
#   def atexitend():
#       self.endDayOAM()

    def _check_and_refresh_access_token(self):
        """
        Check and refresh the access token if needed.
        """
        if self._dbx is None:
            return

        try:
            self._dbx.check_and_refresh_access_token()

        except AuthError as e:
            rpiLogger.error("rpimgdb::: _check_and_refresh_access_token(): AuthError!\n%s\n", str(e))
            raise rpiBaseClassError("rpimgdb::: _check_and_refresh_access_token(): AuthError!", ERRCRIT)

        except DropboxException as e:
            rpiLogger.error("rpimgdb::: _check_and_refresh_access_token(): DropboxException!\n%s\n", str(e))
            raise rpiBaseClassError("rpimgdb::: _check_and_refresh_access_token(): DropboxException!", ERRCRIT)

        except InternalServerError as e:
            rpiLogger.error("rpimgdb::: _check_and_refresh_access_token(): InternalServerError!\n%s\n", str(e))
            raise rpiBaseClassError("rpimgdb::: _check_and_refresh_access_token(): InternalServerError!",  ERRCRIT)


    def _lsImage(self,from_path):
        """
        List the image/video files in the remote directory.
        Stores the found file names in self.imageDbList.
        """
        if self._dbx is None:
            return
        
        try:
            self._check_and_refresh_access_token()

            if self._imageDbCursor is None:
                self.ls_ref = self._dbx.files_list_folder('/' + os.path.normpath(from_path), recursive=False, include_media_info=True )
            else:
                new_ls = self._dbx.files_list_folder_continue(self._imageDbCursor)
                if new_ls.entries == []:
                    rpiLogger.debug("rpimgdb::: _lsImage(): No changes on the server.")
                else:
                    self.ls_ref = new_ls

            # Select only images and only the ones for the current imgid (camid)
            foundImg = False
            for f in self.ls_ref.entries:
                if 'media_info' in f._all_field_names_ and \
                    f.media_info is not None:
                    if self.imgid.lower() in f.path_lower:
                        img = '.%s' % f.path_lower
                        foundImg = True
                        if not img in self.imageDbList:
                            self.imageDbList.append(img)


            if not foundImg:
                self.imageDbList = []

            ### Store the hash of the folder
            self._imageDbCursor = self.ls_ref.cursor

            if len(self.imageDbList) > 0:
                rpiLogger.debug("rpimgdb::: _lsImage(): imageDbList[0..%d]: %s .. %s", len(self.imageDbList)-1, self.imageDbList[0], self.imageDbList[-1] )
            else:
                rpiLogger.debug("rpimgdb::: _lsImage(): imageDbList[]: empty.")

        except ApiError as err:
            if err.user_message_text:
                rpiLogger.warning("rpimgdb::: _lsImage(): ApiError %s!", err.user_message_text)
                raise rpiBaseClassError(f"rpimgdb::: _lsImage(): ApiError {err.user_message_text}!", ERRLEV2)
            else:
                rpiLogger.warning("rpimgdb::: _lsImage() ApiError %s!", err.error)
                raise rpiBaseClassError(f"rpimgdb::: _lsImage(): ApiError {err.error}!", ERRLEV2)



    def _putImage(self, from_path, to_path, overwrite=False):
        """
        Copy local file to remote file.
        Stores the uploaded files names in self.imageUpldFIFO.

        Examples:
        _putImage('./path/test.jpg', '/path/dropbox-upload-test.jpg')
        """
        if self._dbx is None:
            return

        self._check_and_refresh_access_token()

        mode = (WriteMode.overwrite if overwrite else WriteMode.add)

        with open(from_path, "rb") as from_file:
            try:
                self._dbx.files_upload( from_file.read(), '/' + os.path.normpath(to_path), mode)

                if not overwrite:
                    self.imageUpldFIFO.append(from_path)

                rpiLogger.debug("rpimgdb::: _putImage(): Uploaded file from %s to remote %s", from_path, to_path)

            except ApiError as err:
                # This checks for the specific error where a user doesn't have
                # enough Dropbox space quota to upload this file
                if (err.error.is_path() and err.error.get_path().error.is_insufficient_space()):
                    rpiLogger.error("rpimgdb::: _putImage(): ApiError Cannot back up; insufficient space!\n%s\n", str(err))
                    raise rpiBaseClassError("rpimgdb::: _putImage(): ApiError Cannot back up; insufficient space!", ERRCRIT)
                elif err.user_message_text:
                    rpiLogger.warning("rpimgdb::: _putImage(): ApiError %s!", err.user_message_text)
                    raise rpiBaseClassError(f"rpimgdb::: _putImage(): ApiError {err.user_message_text}!", ERRLEV2)
                else:
                    rpiLogger.warning("rpimgdb::: _putImage(): ApiError %s!", err.error)
                    raise rpiBaseClassError(f"rpimgdb::: _putImage(): ApiError {err.error}!", ERRLEV2)

            #except IOError:
                #raise rpiBaseClassError(f"rpimgdb::: _putImage(): Local img file {from_path} could not be opened!", ERRCRIT)

    def _mkdirImage(self, path):
        """
        Create a new remote directory.

        Examples:
        _mkdirImage('/dropbox_dir_test')
        """
        if self._dbx is None:
            return

        self._check_and_refresh_access_token()

        try:
            self._dbx.files_create_folder('/' + os.path.normpath(path))

            rpiLogger.debug("rpimgdb::: _mkdirImage(): Remote output folder /%s created.", path)

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
                        rpiLogger.info("rpimgdb::: Remote output folder /%s already exist!", path)
                        noerr = True

            if not noerr:
                rpiLogger.error("rpimgdb::: _mkdirImage(): ApiError Remote output folder /%s was not created!\n%s\n", path, str(e))
                raise rpiBaseClassError(f"rpimgdb::: _mkdirImage(): ApiError Remote output folder /{path} was not created!", ERRCRIT)
            else:
                pass


    def _mvImage(self, from_path, to_path):
        """
        Move/rename a remote file or directory.

        Examples:
        _mvImage('./path1/dropbox-move-test.jpg', '/path2/dropbox-move-test.jpg')
        """
        if self._dbx is None:
            return

        self._check_and_refresh_access_token()

        try:
            self._dbx.files_move( '/' + os.path.normpath(from_path), '/' +  os.path.normpath(to_path) )

            rpiLogger.debug("rpimgdb::: _mvImage(): Moved file from %s to %s", from_path, to_path)

        except ApiError as e:
            rpiLogger.error("rpimgdb::: _mvImage(): ApiError Image %s could not be moved to %s!\n%s\n", from_path, to_path, str(e))
            raise rpiBaseClassError(f"rpimgdb::: _mvImage(): ApiError Image {from_path} could not be moved to {to_path}!", ERRLEV2)


#   def _getImage(self, from_file, to_path):
#       """
#       Copy file from remote directory to local file.
#
#       Examples:
#       _getImage('./path/dropbox-download-test.jpg', './file.jpg',)
#       """
#       try:
#           metadata, response  = self._dbx.files_download_to_file( to_path, '/' + os.path.normpath(from_file) )
#           rpiLogger.debug("rpimgdb::: _getImage(): Downloaded file from remote %s to %s. Metadata: %s", from_file, to_path, metadata)
#
#       except ApiError as e:
#           raise rpiBaseClassError(f"rpimgdb::: _getImage(): ApiError {e.error}!", ERRLEV2)


#   def _searchImage(self, string):
#       """
#       Search remote directory for image/video filenames containing the given string.
#       """
#       try:
#           results = self._dbx.files_search( '', string, start=0, max_results=100, mode=SearchMode('filename', None) )
#
#       except ApiError as e: #rest.ErrorResponse as e:
#           raise rpiBaseClassError("rpimgdb::: _searchImage(): ApiError {e.error}!", ERRLEV2)


#   def _rmImage(self, path):
#       """
#       Delete a remote image/video file
#       """
#
