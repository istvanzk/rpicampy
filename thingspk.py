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

A simple REST request abstraction layer and a light ThingSpeak API SDK, 
according to the API documentation at http://community.thingspeak.com/documentation/api/
and the TalkBack API documentation at https://thingspeak.com/docs/talkback

The REST client implementation is based on the official python Xively API client (SDK).

The Channel ID and API Key(s) are read from the text file given as argument when the class is instantiated.
"""

import sys
import time
from urllib.parse import urljoin
#import urlparse
from requests.sessions import Session
from threading import Thread, Semaphore, Event
from queue import Queue
import logging

#import unittest

try:
	import json
except ImportError:
	import simplejson as json

SDK_VERSION = 0.8
TINTV_CH_SEC = 300
TINTV_TB_SEC = 300
	
class RESTClient(Session):
	"""
	Implements a REST client Session object

	This is instantiated with an API key which is used for all requests to the
	ThingSpeak API.  It also defines a BASE_URL so that we can specify relative urls
	when using the client (all requests via this client are going to ThingSpeak).

	:param use_ssl: Use https for all connections instead of http
	:type use_ssl: bool [False]
	:param verify: Verify SSL certificates
	:type verify: bool [True] 
	:param raw_response: Raw response from the http request
	:type raw_response: bool [False] 
 
	Usage::
	
		APIClient = RESTClient(use_ssl=True)

	"""

	BASEAPI_URL = "//api.thingspeak.com"
	BASE_URL = "//thingspeak.com"
		
	def __init__(self, use_ssl=False, verify=True, text_response=False):
		super(RESTClient, self).__init__()
		self.apiport = (443 if use_ssl else 80)
		self.base_url = ('https:' if use_ssl else 'http:') + self.BASE_URL
		self.baseapi_url = ('https:' if use_ssl else 'http:') + self.BASEAPI_URL
		self.baseapi_url += ':{}'.format(self.apiport)
		self.headers['Content-Type'] = "application/x-www-form-urlencoded"
		self.headers['Accept'] = "text/plain"
		self.headers['User-Agent'] = "UnOfficialThingSpeakPython SDK v{}".format(SDK_VERSION)
		self.verify = verify	
		self.text_response = text_response	
        
	def request(self, method, url, **kwargs):
		"""
		Constructs and sends a Request to the ThingSpeak API.

		Objects that implement __getstate__  will be serialised.
	
		**kwargs is a dict of the keyword args passed to the request() function
		"""

		assert method in ['GET','PUT','POST'], "Only 'GET', 'PUT' and 'POST' are allowed."
		if 'params' not in kwargs:
			raise RESTClientError('The params entry was not set!')

		full_url = urljoin(self.baseapi_url, url)

		# JSON data
		#if 'data' in kwargs:
		#    kwargs['data'] = self._jsonencode_data(kwargs['data'])
		
		# Call the request() from requests/api.py
		resp = super(RESTClient, self).request(method, full_url, **kwargs)
		resp.raise_for_status()
		
		# Process the response
		if resp.status_code != 200:
			raise RESTClientErrorResponse(resp)

		if self.text_response:
			super(RESTClient, self).close()
			return resp.text
			
		else:
			try:
				respjson = resp.json()
			except ValueError:
				raise RESTClientErrorResponse(resp)
			finally:
				super(RESTClient, self).close()		
		
			return respjson
		
class RESTClientError(Exception):
	"""
	Raised by RESTCLient.request when incorrect input parameters are detected
	"""

	def __init__(self, err):
		msg = "RESTCLient error: %s" % err

	def __str__(self):
		return msg

class RESTClientErrorResponse(Exception):
    """
    Raised by RESTClient.request for requests that:
    - Return a non-200 HTTP response, or
    - Have a non-JSON response body, or
    - Have a malformed/missing header in the response.
    """

    def __init__(self, http_resp):
        self.status = http_resp.status_code
        self.body = http_resp.text
        self.reason = 'Unknown'
        self.headers = http_resp.headers

        try:
            self.body = http_resp.json()
            self.error_msg = self.body.get('error')
            self.user_error_msg = self.body.get('user_error')
        except ValueError:
            self.error_msg = None
            self.user_error_msg = None

    def __str__(self):
        if self.user_error_msg and self.user_error_msg != self.error_msg:
            # one is translated and the other is English
            msg = "%s (%s)" % (self.user_error_msg, self.error_msg)
        elif self.error_msg:
            msg = self.error_msg
        elif not self.body:
            msg = self.reason
        else:
            msg = "Error parsing response body or headers: " +\
                  "Body - %s Headers - %s" % (self.body, self.headers)

        return "[%d] %s" % (self.status, repr(msg))

	
class ThingSpeakTBTimer(Thread):
	"""
	Implements a Timer/intervalometer class to listen to TalkBack commands at pre-set time intervals
	"""	
	def __init__(self, tspk_talkback, dict_tconfig):
		Thread.__init__(self)
		self.daemon = True
		self.name   = "tspkTBTimer"	
				
		self.talkback = tspk_talkback
		self.config = dict_tconfig	

		# Queue for the received commands
		self.cmdrx = Queue.Queue()
		
		### Stop and Active events				
		self.Stop = Event()
		self.Stop.clear()
		self.Active = Event()
		self.Active.clear()
		
		### Configuration
		self.tintv_sec = self.config.get('tintv_sec')
		if self.tintv_sec is None or \
			self.tintv_sec <= 0:
			self.tintv_sec = TINTV_TB_SEC
			
		### Count the command events: [CmdRx, CmdTx]
		self.eventCounters = [0,0]
	
	def __str__(self):
		return "%s:::\n\tconfig:%s\n\teventCounters:%s\n\ttintv_sec:%s" % \
			(self.name, self.config, str(self.eventCounters), str(self.tintv_sec))
				
	def run(self):
		"""
		The TB timer loop
		"""
		while not self.Stop.is_set():
		
			#print("\nSleep...")
			time.sleep(self.tintv_sec)	
		
			if self.Active.is_set():	
				#print("\nCheck is active")
		
				# Check for RX cmd
				self.talkback.execcmd()
				if self.talkback.response:
					self.cmdrx.put(self.talkback.response)
					self.eventCounters[0] += 1
					#print("\nCmd rx")
				#else:
				#	self.cmdrx.put(None)
				
				# TX cmd?	
			else:
				print("\nCheck is not active")
			
	def stop(self):
		"""
		Stop the ThingSpeak TBTimer thread
		"""	
		self.Stop.set()
	
	def setintv(self, tintv_sec):
		"""
		Set the time interval for the TBTimer
		"""	
		self.tintv_sec = tintv_sec
			
	def enable(self):
		"""
		Activate the ThingSpeak TBTimer
		"""	
		self.Active.set()
			
	def disable(self):
		"""
		De-activate the ThingSpeak TBTimer
		"""	
		self.Active.clear()
			
class ThingSpeakTBClient(object):
	"""
	The API root object from which the user can manage TalkBack apps.
	The TalkBack apps are managed via the class:TalkBacksManager instances.
	Uses class:RESTClient instance.

	:param key_file: the ThingSpeak API keys file
	:type key_file: string
	:param use_ssl: Use https for all connections instead of http
	:type use_ssl: bool [False]
	:param text_response: Use text format for all the request() responses 
	:type text_response: bool [False]
	:param tconfig: configuration parameters for timer/intervalometer
	:type tconfig: dictionary [None]

	Usage::
		tspk = thingspk.ThingSpeakTBClient('keys_file.txt')
		tspk.talkback.
		print tspk.talkback.response	

	"""
	client_class = RESTClient

	def __init__(self, key_file=None, use_ssl=True, text_response=False, tconfig=None ):
		self.key_file = key_file or None
		self.tconfig = tconfig or None
	
		if self.key_file is None:
			logging.error("ThingSpeak TB::: No TalkBack ID and API Key were specified! Exiting!", exc_info=True)	
		
		# Read the access key
		try:
			with open(self.key_file,'r') as f:
				tspk_info = f.read().split('\n')
				tspk_key  = tspk_info[1].split(',',3)
				
				self.talkback_id = int(tspk_key[0])
				self.tbapi_key   = tspk_key[1]
				
		except IOError:
			logging.error("ThingSpeak TB::: Keys file ''%s'' not found! Exiting!" % (self.key_file), exc_info=True)
			raise
		
		# REST client
		self.client = self.client_class(use_ssl=use_ssl, text_response=text_response)			

		# TalkBack manager
		self._talkback = None
		if self.talkback_id is not None and \
			self.tbapi_key is not None:
			self._talkback = TalkBacksManager(self.client, self.talkback_id, self.tbapi_key)
		
		# Timer (intervalometer) for TalkBack cmds			
		self._timer = None			
		if (self._talkback is not None) and \
			(self.tconfig is not None) and \
			(self.tconfig.get('enabled') is not None) and \
			self.tconfig.get('enabled')==True:

			self._timer = ThingSpeakTBTimer(self._talkback, self.tconfig)
			
			#print self._timer			
						
	@property
	def talkback(self):
		"""
		Access :class:`.TalkBack` objects through a :class:`.TalkBacksManager`.
		TalkBack = API allows any device to act upon queued commands.
		"""
		return self._talkback
		
	@property
	def timer(self):
		"""
		Access :class:`.TBTimer` objects through a :class:`.ThingSpeakTBTimer`.
		TalkBack timer = listen to TalkBack commands at pre-set time intervals.
		"""
		return self._timer

						
class ThingSpeakCHTimer(Thread):
	"""
	Implements a Timer/intervalometer class to update ThingSpeak feed(s)/channel(s)
	and to listen to TalkBack commands at pre-set time intervals
	"""	
	def __init__(self, tspk_channel, dict_tconfig, tspk_events ):
		threading.Thread.__init__(self)
		self.name   = "tspkCHTimer"	
				
		self.channel = tspk_channel		
		self.config = dict_tconfig			
		self.events = tspk_events

		### Stop event		
		self.Stop = Event()
		self.Stop.clear()
		self.Active = Event()
		self.Active.clear()
		
		### Configuration
		self.config = dict_tconfig	
		self.tintv_sec = self.config.get('tintv_sec')
		if self.tintv_sec is None or \
			self.tintv_sec <= 0:
			self.tintv_sec = TINTV_CH_SEC

		### Count the feed and status updates: [Feed, Status]
		self.eventCounters = [0,0]

	def __str__(self):
		return "%s::: config:%s\neventCounters:%s" % \
			(self.name, self.config, str(self.eventCounters))

	def run(self):
		### The CH timer loop
		while not self.Stop.is_set():
		
			time.sleep(self.tintv_sec)	
			
			if self.events.is_set():
				# Update feed
				self.channel.postupdates()
				self.eventCounters[0] += 1
			
				self.channel.getfield('status')
				if self.channel.response:
					self.channel.setfield('status','')
					self.eventCounters[1] += 1
						
		# End
		
	def stop(self):
		"""
		Stop the ThingSpeak CHTimer thread
		"""	
		self.Stop.set()
	
	def setintv(self, tintv_sec):
		"""
		Set the time interval for the CHTimer
		"""	
		self.tintv_sec = tintv_sec
			
	def enable(self):
		"""
		Activate the ThingSpeak CHTimer
		"""	
		self.Active.set()
			
	def disable(self):
		"""
		De-activate the ThingSpeak CHTimer
		"""	
		self.Active.clear()
			
class ThingSpeakAPIClient(object):
	"""
	The API root object from which the user can manage channels and charts.
	The Channels and Charts are managed via the class:ChannelsManager and 
	class:ChartsManager instances.
	Uses class:RESTClient instance.

	:param key_file: the ThingSpeak API channel IDs and Keys file
	:type key_file: string
	:param use_ssl: Use https for all connections instead of http
	:type use_ssl: bool [False]
	:param text_response: Use text format for all the request() responses 
	:type text_response: bool [False]
	:param tconfig: configuration parameters for timer/intervalometer
	:type tconfig: dictionary [None]

	Usage::
		tspk = thingspk.ThingSpeakAPIClient('keys_file.txt')
		tspk.channel.getuserinfo(username='user0')
		print tspk.channel.response	

	"""
	client_class = RESTClient

	def __init__(self, key_file=None, use_ssl=True, text_response=False, tconfig=None ):
		self.key_file = key_file or None
		self.tconfig = tconfig or None
		
		if self.key_file is None:
			logging.error("ThingSpeak API::: No Channel ID and API Keys were specified! Exiting!", exc_info=True)	
			
		# Read the Channel ID and API Key
		try:
			with open(self.key_file,'r') as f:
				tspk_info = f.read().split('\n')
				tspk_key  = tspk_info[0].split(',',3)
				
				self.channel_id = int(tspk_key[0])
				self.write_key  = tspk_key[1]
				self.read_key   = tspk_key[2]
				
		except IOError:
			logging.error("ThingSpeak API::: Keys file ''%s'' not found! Exiting!" % (self.key_file), exc_info=True)
			raise

		# REST client
		self.client = self.client_class(use_ssl=use_ssl, text_response=text_response)
						
		# Channel manager
		self._channel =  None	
		if self.client is not None and \
			self.channel_id is not None:	
			self._channel = ChannelsManager(self.client, self.channel_id, self.write_key)
						
		# Charts manager
		self._chart = None
		#self._chart = ChartsManager(self.client, self.channel_id, self.read_key)
		
		# Timer (intervalometer) for channel updates
		self._timer = None
		if (self.tconfig is not None) and \
			(self.tconfig.get('enabled') is not None) and \
			self.tconfig.get('enabled')==True:
			
			self._events.Active = Event()
			self._events.Active.clear()
			self._timer = ThingSpeakCHTimer(self._channel, self.tconfig, self._events)
			
		
	def __repr__(self):
		return "<{}.{}()>".format(__package__, self.__class__.__name__)


	def setfield(self, field_id, field_value):
		"""
		Expose the _channel.setfield() method
		Set field data of the current channel
		"""
		self._channel.setfield(field_id, field_value)
	
	def update(self):
		"""
		Expose the _channel.postupdates() method
		Update and post all fields of the current channel
		"""
		self._channel.postupdates()
		
					
	@property
	def channel(self):
		"""
		Access :class:`.Channels` objects through a :class:`.ChannelsManager`.
		Channel = The name for where data can be inserted or retrieved within the 
		ThingSpeak API, identified by a numerical Channel ID
		"""
		return self._channel

	@property
	def chart(self):
		"""
		Access :class:`.Charts` objects through a :class:`.ChartsManager`.
		Chart = API allows you to create an instant visualization of your data
		"""
		return self._chart


class ManagerBase(object):
	"""Abstract base class for all of ThingSpeak manager classes."""

	@property
	def base_url(self):
		if getattr(self, '_base_url', None) is not None:
			return self._base_url
		parent = getattr(self, 'parent', None)
		if parent is None:
			return
		manager = getattr(parent, '_manager', None)
		if manager is None:
			return
		base_url = manager.url(parent.id) + '/' + self.resource
		return base_url

	@base_url.setter  # NOQA
	def base_url(self, base_url):
		self._base_url = base_url

	def url(self, id_or_url=None):
		"""Return a url relative to the base url."""
		url = self.base_url
		if id_or_url:
			url = urljoin(url, str(id_or_url))
		return url

	def mkparams(self, keystr=None, **data):
		# build params
		kwargs = {}
		kwargs['params'] = {}
		for key in data:
			kwargs['params'][key] = data[key]
		
		# add the API key
		keystr = keystr or {}			
		if keystr:			
			kwargs['params']['api_key'] = keystr	
		else:
			kwargs['params']['api_key'] = self.wkey	
													
		return kwargs

	def mktbparams(self, **data):
		# build params
		kwargs = {}
		kwargs['params'] = {}
		for key in data:
			kwargs['params'][key] = data[key]
		
		# add the Talkback API key
		kwargs['params']['api_key'] = self.tbkey	
													
		return kwargs
	
	def _parse_datetime(self, value):
		"""Parse and return a datetime string from the Thingspeak API."""
		return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")

	def _prepare_params(self, params):
		"""Prepare parameters to be passed in query strings to the Thingspeak API."""
		params = dict(params)
		for name, value in params.items():
			if isinstance(value, datetime):
				params[name] = value.isoformat() + 'Z'
		return params
				
class TalkBacksManager(ManagerBase):
	"""
	Create, update and return ThingSpeak TalkBack objects.

	This manager should live on a :class:`.ThingSpeakAPIClient` instance and not 
	instantiated directly.

	:param client: Low level :class:`.RESTClient` instance
	:param talkback_id: The ThingSpeak TalkBack ID
	:param tbkey: the TalkBack API Key

	Usage::
		APIClient = RESTClient(use_ssl=use_ssl, text_response=text_response)
		APITalkback = TalkBacksManager(APIClient,talkback_id,'talkback_api_key')

	"""

	def __init__(self, client, talkback_id, tbkey):
		self.client = client or None
		self.talkback_id = talkback_id or None
		self.tbkey = tbkey or None		
				
		self.base_url = urljoin(client.baseapi_url , 'talkbacks/' + str(self.talkback_id))
		# The self.response format depends on the self.client.text_format flag
		self.response = {}
		
	
	def addcmd(self, command_string, position, format='json'):	
		"""
		Add a TalkBack Command.
		The response will be the command ID or a JSON object.
		URL: https://api.thingspeak.com/talkbacks/TALKBACK_ID/commands
		
		:param api_key (string): API key for this specific TalkBack (required)
		:param command_string (string): Command to be sent to your device. 
			There is a limit of 255 characters per command_string.
		:param position (integer): The position you want this command to appear in. 
			Any previous commands at or after this position will be shifted down. 
			If the position is left blank, the command will automatically be added 
			to the end of the queue (with the highest position).
		
		"""
		data = {'command_string': command_string, 'position': position}
		kwargs = self.mktbparams(**data)
		url = self.base_url + '/commands' + '.' + format
				
		self.response = self.client.post(url, data=None, **kwargs)		
		
	def getcmd(self, command_id, format='json'):	
		"""
		Show an existing TalkBack command.
		The response will be the command string or a JSON object.
		URL: https://api.thingspeak.com/talkbacks/TALKBACK_ID/commands/COMMAND_ID
		
		:param api_key (string): API key for this specific TalkBack (required)
		"""
		kwargs = {}
		kwargs['params'] = {}		
		kwargs['params']['api_key'] = self.tbkey
		url = self.base_url + '/commands/' + str(command_id) + '.' + format
				
		#print url 
				
		self.response = self.client.get(url, **kwargs)		
		
	def updatecmd(self, ommand_string, position, command_id, format='json'):	
		"""
		Update an existing TalkBack command.
		The response will be the command string or a JSON object.
		URL: https://api.thingspeak.com/talkbacks/TALKBACK_ID/commands/COMMAND_ID
		
		:param api_key (string): API key for this specific TalkBack (required)
		:param command_string (string): Command to be sent to your device. 
			There is a limit of 255 characters per command_string.
		:param position (integer): The position you want this command to appear in. 
			Any previous commands at or after this position will be shifted down. 
		"""
		data = {'command_string': command_string, 'position': position}
		kwargs = self.mktbparams(**data)		
		url = self.base_url + '/commands/' + str(command_id) + '.' + format
				
		self.response = self.client.put(url, data=None, **kwargs)

	def execcmd(self, format='json'):	
		"""
		Execute the next TalkBack command in the queue (normally in position 1).
		Executing a command removes it from the queue, sets executed_at to the current time, 
		sets position to null, and reorders the remaining commands. 
		The response will be the command string or a JSON object.
		If there are no commands left to execute, the response body will be empty.
		URL: https://api.thingspeak.com/talkbacks/TALKBACK_ID/commands/execute

		:param api_key (string): API key for this specific TalkBack (required)		
		"""
		kwargs = {}
		kwargs['params'] = {}		
		kwargs['params']['api_key'] = self.tbkey
		url = self.base_url + '/commands/execute' + '.' + format
				
		self.response = self.client.get(url, **kwargs)		

	def getexeccmd(self, format='json'):	
		"""
		Show the most recently executed TalkBack command.
		The response will be the command string or a JSON object.
		URL: https://api.thingspeak.com/talkbacks/TALKBACK_ID/commands/last

		:param api_key (string): API key for this specific TalkBack (required)		
		"""
		kwargs = {}
		kwargs['params'] = {}		
		kwargs['params']['api_key'] = self.tbkey
		url = self.base_url + '/commands/last' + '.' + format
				
		self.response = self.client.get(url, **kwargs)		
										
	def execcmd_updatech(self, format='json'):	
		"""
		The next TalkBack command in the queue (normally in position 1) can be executed. 
		at the same time a Channel is updated.
		URL: https://api.thingspeak.com/update
		
		:param api_key (string): API key for the Channel (required)				
		:param talkback_key (string) - API key for this specific TalkBack (required)
		"""			
		kwargs = {}
		kwargs['params'] = {}							
		if self.wkey:
			kwargs['params']['api_key'] = self.wkey
			kwargs['params']['talkback_key'] = self.tbkey
			url = urljoin(self.client.baseapi_url + '/update' + '.' + format)
				
			self.response = self.client.get(url, **kwargs)
																			
class ChannelsManager(ManagerBase):
	"""
	Create, update and return ThingSpeak Channel objects (and fields).

	This manager should live on a :class:`.ThingSpeakAPIClient` instance and not 
	instantiated directly.

	:param client: Low level :class:`.RESTClient` instance
	:param channel_id: The ThingSpeak Channel ID
	:param wkey: the Write API Key

	Usage::
		APIClient = RESTClient(use_ssl=use_ssl, text_response=text_response)
		APIChannels = ChannelsManager(APIClient,'channelName','write_api_key')
		fielddata = {'field1':9, 'field2':-7, 'status': '4 update'}
		APIChannels.postupdates(**fielddata)
		print APIChannels.response

	"""
	
	def __init__(self, client, channel_id, wkey):
		self.client = client
		self.channel_id = channel_id
		self.wkey = wkey
		self.base_url = client.baseapi_url
	
		self.channeldata = {}
		self.chdata_semaphore = Semaphore()				
	
		# The self.response format depends on the self.client.text_format flag
		self.response = {}

	def setfield(self, field_id, field_value):
		"""
		Set the specified field's value in channeldata
		"""
		self.chdata_semaphore.acquire()
		self.channeldata[field_id] = field_value
		self.chdata_semaphore.release()

	def getfield(self, field_id):
		"""
		Get the specified field's value in channeldata
		"""
		self.chdata_semaphore.acquire()
		self.response = self.channeldata[field_id]
		self.chdata_semaphore.release()
		
	def postupdates(self):
		"""
		Updates an existing Channel identified by its Write API key.
		URL: http://api.thingspeak.com/update

		:param **data: The optional kwarg with parameters (see below)
		
		Optional Field parameters:
			'field1': 12, 'field2': 11
		Optional Location parameters:
			'lat' : [Latitude in decimal degrees]
			'long': [Longitude in decimal degrees]
			'elevation": [Elevation in meters]	
		Optional Status parameters:
			'status': [Status Update]
		Optional Twitter Parameters:
			'twitter': [Twitter Username linked to ThingTweet]
			'tweet': [Twitter Status Update]

		"""
		# Content of channeldata is posted
		url = self.url('update')
#		if data:
#			self.chdata_semaphore.acquire()
#			for key, value in data.iteritems():
#				self.channeldata[key] = value
#			self.chdata_semaphore.release()
							
		if self.channeldata:
			self.chdata_semaphore.acquire()			
			kwargs = self.mkparams(**self.channeldata)
			self.chdata_semaphore.release()
			
		else:
			kwargs = {}
															
		"""
		[requests.api.py]
		Sends a POST request. Returns :class:`Response` object.

		:param url: URL for the new :class:`Request` object.
		:param data: (optional) Dictionary, bytes, or file-like object to send in 
					the body of the :class:`Request`.
		:param **kwargs: Optional arguments that ``request`` takes 

		"""
		self.response = self.client.post(url, data=None, **kwargs)
		

	def getfeeds(self, rkey=None, channel_id=None, format='json', **opt):
		"""
		Retrieves Channel Feeds in the specified Format		
		URL: http://api.thingspeak.com/channels/(channel_id)/feed.(format)

		:param rkey: The optional Read API key
		:type rkey: string
		:param channel_id: The optional Channel ID
		:type channel_id: string
		:param format: The optional format id for the returned data: 'json', 'xml', 'csv'
		:type format: string
		:param **opt: The optional kwarg with parameters (see below)
		
		Optional parameters in **opt:	
			results=[number of entries to retrieve (8000 max)]
			days=[days from now to include in feed]
			start=[start date] – YYYY-MM-DD HH:NN:SS
			end=[end date] - YYYY-MM-DD HH:NN:SS
			offset=[timezone offset in hours]
			status=true (include status updates in feed)
			location=true (include latitude, longitude, and elevation in feed)
			min=[minimum value to include in response]
			max=[maximum value to include in response]
			round=x (round to x decimal places)
			timescale=x (get first value in x minutes, valid values: 10, 15, 20, 30, 60, 240, 720, 1440)
			sum=x (get sum of x minutes, valid values: 10, 15, 20, 30, 60, 240, 720, 1440)
			average=x (get average of x minutes, valid values: 10, 15, 20, 30, 60, 240, 720, 1440)
			median=x (get median of x minutes, valid values: 10, 15, 20, 30, 60, 240, 720, 1440)

		"""
		channel_id = channel_id or self.channel_id
		kwargs = self.mkparams(rkey, **opt)

		url = self.url( 'channels/' + str(channel_id) + '/feed.' + format )

		self.response = self.client.get(url, **kwargs)

	def getlastentry(self, rkey=None, channel_id=None, format='json', **opt):
		"""
		Retrieves the Last Entry in Channel Feed in the specified Format		
		URL: http://api.thingspeak.com/channels/(channel_id)/feed/last.(format)

		:param rkey: The optional Read API key
		:type rkey: string
		:param channel_id: The optional Channel ID
		:type channel_id: string
		:param format: The optional format id for the returned data: 'json', 'xml', 'csv'
		:type format: string
		:param **opt: The optional kwarg with parameters (see below)

		Optional parameters in **opt:				
			offset=[timezone offset in hours]
			status=true (include status updates in feed)
			location=true (include latitude, longitude, and elevation in feed)
			callback=[function name] (used for JSONP cross-domain requests)

		"""
		channel_id = channel_id or self.channel_id
		kwargs = self.mkparams(rkey, **opt)

		url = self.url( 'channels/' + str(channel_id) + '/feed/last.' + format )

		self.response = self.client.get(url, **kwargs)

	def getfeedfield(self, field_id, rkey=None, channel_id=None, format='json', **opt):
		"""
		Retrieves a Field Feed in the specified Format
		URL: http://api.thingspeak.com/channels/(channel_id)/field/(field_id).(format)  

		:param field_id: The mandatory field id
		:type format: string
		:param rkey: The optional Read API key
		:type rkey: string
		:param channel_id: The optional Channel ID
		:type channel_id: string
		:param format: The optional format id for the returned data: 'json', 'xml', 'csv'
		:type format: string
		:param **opt: The optional kwarg with parameters (see below)
			
		Optional parameters in **opt:				
			results=[number of entries to retrieve (8000 max)]
			days=[days to include in feed]
			start=[start date] - YYYY-MM-DD%20HH:NN:SS
			end=[end date] - YYYY-MM-DD%20HH:NN:SS
			offset=[timezone offset in hours]
			status=true (include status updates in feed)
			location=true (include latitude, longitude, and elevation in feed)
			min=[minimum value to include in response]
			max=[maximum value to include in response]
			round=x (round to x decimal places)
			timescale=x (get first value in x minutes, valid values: 10, 15, 20, 30, 60, 240, 720, 1440)
			sum=x (get sum of x minutes, valid values: 10, 15, 20, 30, 60, 240, 720, 1440)
			average=x (get average of x minutes, valid values: 10, 15, 20, 30, 60, 240, 720, 1440)
			median=x (get median of x minutes, valid values: 10, 15, 20, 30, 60, 240, 720, 1440)
			callback=[function name] (used for JSONP cross-domain requests)

		"""
		channel_id = channel_id or self.channel_id
		kwargs = self.mkparams(rkey, **opt)

		url = self.url( 'channels/' + str(channel_id) + '/field/' + field_id + '.' + format )

		self.response = self.client.get(url, **kwargs)

	def getfeedlastentry(self, field_id, rkey=None, channel_id=None, format='json', **opt): 
		"""
		Retrieves the last Entry in a Field Feed in the specified Format
		URL: http://api.thingspeak.com/channels/(channel_id)/field/(field_id)/last.(format)  

		:param field_id: The mandatory field id
		:type format: string
		:param rkey: The optional Read API key
		:type rkey: string
		:param channel_id: The optional Channel ID
		:type channel_id: string
		:param format: The optional format id for the returned data: 'json', 'xml', 'csv'
		:type format: string
		:param **opt: The optional kwarg with parameters (see below)

		Optional parameters in **opt:
			offset=[timezone offset in hours]
			status=true (include status updates in feed)
			location=true (include latitude, longitude, and elevation in feed)
			callback=[function name] (used for JSONP cross-domain requests)
		
		"""
		channel_id = channel_id or self.channel_id
		kwargs = self.mkparams(rkey, **opt)

		url = self.url( 'channels/' + str(channel_id) + '/field/' + field_id + '/last.' + format )

		self.response = self.client.get(url, **kwargs)

	def getstatus(self, rkey=None, channel_id=None, format='json', **opt):
		"""
		Retrieves Status Updates in the specified Format		
		URL: http://api.thingspeak.com/channels/(channel_id)/status.(format)

		:param field_id: The mandatory field id
		:type format: string
		:param rkey: The optional Read API key
		:type rkey: string
		:param channel_id: The optional Channel ID
		:type channel_id: string
		:param format: The optional format id for the returned data: 'json', 'xml', 'csv'
		:type format: string
		:param **opt: The optional kwarg with parameters (see below)

		Optional parameters in **opt:
			offset=[timezone offset in hours]
			callback=[function name] (used for JSONP cross-domain requests)		

		"""
		channel_id = channel_id or self.channel_id
		kwargs = self.mkparams(rkey, **opt)

		url = self.url( 'channels/' + str(channel_id) + '/status.' + format )

		self.response = self.client.get(url, **kwargs)

	def getpubchannels(self, format='json', **opt):        
		"""
		List Public Channels in the specified Format
		URL: http://api.thingspeak.com/channels/public.(format)
	
		:param format: The optional format id for the returned data: 'json', 'xml', 'csv'
		:type format: string
		:param **opt: The optional kwarg with parameters (see below)
		
		Optional parameters in **opt:
			page=[page number to retrieve]
			tag=[name of tag to search for, should be URL encoded]

		"""

		url = self.url( 'channels/public.' + format )

		self.response = self.client.get(url, **kwargs)

	def getuserinfo(self, ukey=None, username=None, format='json'):                
		"""
		List user information
		URL: http://api.thingspeak.com/users/(username).(format)
		
		:param ukey: The optional User API key
		:type ukey: string
		:param username: The optional Channel ID
		:type username: string
		:param format: The optional format id for the returned data: 'json', 'xml', 'csv'
		:type format: string
		
		"""
		kwargs = self.mkparams(ukey)

		url = self.url( 'users/' + username + '.' + format )
		
		self.response = self.client.get(url, **kwargs)

	def getuserchannels(self, ukey=None, username=None, format='json'):                
		"""
		List user's channels
		URL: http://api.thingspeak.com/users/(username)/channels.(format)

		:param ukey: The optional User API key
		:type ukey: string
		:param username: The optional Channel ID
		:type username: string
		:param format: The optional format id for the returned data: 'json', 'xml', 'csv'
		:type format: string
		
		"""
		kwargs = self.mkparams(ukey)

		url = self.url( 'users/' + username + '/channels.' + format )
		
		self.response = self.client.get(url, **kwargs)

class ChartsManager(ManagerBase):
	"""
	Create and return ThingSpeak Chart objects.
		
	The Chart API allows you to create an instant visualization of your data. 
	The chart displays properly in all modern browsers and mobile devices. 
	The chart can also show dynamic data by loading new data automatically.
	To place a ThingSpeak Chart on your webpage, use the Chart API as the source of 
	an iframe.

	URL: http://api.thingspeak.com/channels/(channel_id)/charts/(field_id)
	
	:param field_id: The mandatory field id
	:type format: string
	:param rkey: The optional Read API key
	:type rkey: string
	:param channel_id: The optional Channel ID
	:type channel_id: string
	:param **opt: The optional kwarg with parameters (see below)	

	Optional Chart Parameters:
		title=[chart title, default: channel name]
		xaxis=[chart’s x-axis label, default: Date]
		yaxis=[chart’s y-axis label, default: field name]
		color=[line color, default: red]
		bgcolor=[background color, default: white]
		type=[line, bar, or column, default: line]
		width=x (chart width in pixels, iframe width will be 20px larger, default chart width: 400)
		height=x (chart height in pixels, iframe height will be 20px larger, default chart height: 200)
		dynamic=[true or false, default: false] (make chart update automatically every 15 seconds)
		step=[true or false, default: false] (draw chart as a step chart)
		export=[true or false, default: false] (show export buttons, so that chart can be saved as image)

	Optional Feed Parameters:
		results=[number of entries to retrieve (8000 max)]
		days=[days to include in feed]
		start=[start date] - YYYY-MM-DD HH:NN:SS
		end=[end date] - YYYY-MM-DD HH:NN:SS
		offset=[timezone offset in hours]
		status=true (include status updates in feed)
		location=true (include latitude, longitude, and elevation in feed)
		min=[minimum value to include in response]
		max=[maximum value to include in response]
		round=x (round to x decimal places)
		timescale=x (get first value in x minutes, valid values: 10, 15, 20, 30, 60, 240, 720, 1440)
		sum=x (get sum of x minutes, valid values: 10, 15, 20, 30, 60, 240, 720, 1440)
		average=x (get average of x minutes, valid values: 10, 15, 20, 30, 60, 240, 720, 1440)
		median=x (get median of x minutes, valid values: 10, 15, 20, 30, 60, 240, 720, 1440)

	Usage::
		APIClient = RESTClient(use_ssl=use_ssl, text_response=text_response)	
		APICharts = ChartsManager(APIClient, 'channelName', 'read_api_key')
		chartopt = {'width':100, 'heoght':50, 'export':'true'} 
		APICharts.makechart('field_id', **chartopt)
		print APICharts.iframe
			
	"""

	def __init__(self, client, channel_id, rkey):
		self.channel_id = channel_id
		self.rkey = rkey
		self.base_url = client.base_url
		self.iframe = {}
		
	def makechart(self, field_id, **opt):
	
		url = self.url( 'channels/' + str(self.channel_id) + '/charts/' + str(field_id))

		self.mkiframe(url, **opt)
		
		
	def mkiframe(self, url, **data):
	
		self.iframe = "<iframe style=\"border: 1px solid #cccccc;\" src=\"" + url
		self.iframe += "?"
		for key, value in data.iteritems():
			self.iframe += (str(key) + "=" + str(value))
			self.iframe += "&amp;"
		
		self.iframe += "\"></iframe>"



