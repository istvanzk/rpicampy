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
    
Implements the rpiBase class to provide the base with common functionalities for all rpi classes. 	    
"""
import time
import logging
import thingspk


class rpiBaseClassError(Exception):
	"""
	Exception to be raised by a class derived from rpiBaseClass.
	"""

	def __init__(self, errstr, errval):
		self.errmsg = "rpiBaseClass error: %s (%d)" % (errstr, errval)

	def __str__(self):
		return repr(self.msg)

class rpiBaseClass(object):
	"""
	Implements the base class for common functionalities.
	"""
		
	def __init__(self, name, dict_config, rpi_events, restapi=None, restfield=None):
	
		self.name 	 = name
		self._config = dict_config
		
		self._eventDayEnd 	= rpi_events.eventDayEnd				
		self._eventEnd 		= rpi_events.eventEnd
		self._eventErr 		= rpi_events.eventErrList[self.name]
		self._eventErrcount = rpi_events.eventErrcountList[self.name]
		self._eventErrtime 	= rpi_events.eventErrtimeList[self.name]
		self._eventErrdelay	= rpi_events.eventErrdelayList[self.name]
		self.stateVal 		= rpi_events.stateValList[self.name]
						
		self._restapi         = restapi
		self._restapi_fieldid = restfield		
				
		self._state = []
				
		### Init class
		self._initclass()
												
	def __str__(self):
		return "%s::: config: %s\neventErrcount: %d, eventErrtime: %s, eventErrdelay: %s, stateVal: %d" % \
			(self.name, self._config, self._eventErrcount, time.ctime(self._eventErrtime), self._eventErrdelay, self.stateVal)
		
	def __del__(self):
		logging.debug("%s::: Deleted!" % self.name)
			
		### Update REST feed value
		self.restUpdate(-1)


	#
	# Interface methods to be overriden by user defined method.
	#
	def jobRun(self):
		"""
		Main function. To be overriden by user defined method.
		"""
		pass

	def initClass(self):
		""""
		(re)Initialize the class. To be overriden by user defined method.
		"""
		pass
		
	def endDayOAM(self):	
		""""
		End-Of-Day OAM. To be overriden by user defined method.
		"""
		pass

	def endOAM(self):	
		""""
		End OAM. To be overriden by user defined method.
		"""
		pass
			
			
	#
	# Interface methods to be used externally.
	#			
	def setRun(self):
		"""
		Enable Run mode and set flags.
		Return boolean to indicate state change.
		"""
		prev = self._state['run']
		self._state['run']   = True
		self._state['stop']  = False
		self._state['pause'] = False
		self._state['init']  = False
		self._state['cmdval'] = 3

		self._setstate()
		
		logging.debug("%s::: Run state." % self.name)
		
		if prev:
			return False
		else:
			return True

	def setStop(self):
		"""
		Enable Stop mode and set flags.
		Return boolean to indicate state change.
		"""		
		prev = self._state['stop']
		self._state['run']   = False
		self._state['stop']  = True
		self._state['pause'] = False
		self._state['init']  = False
		self._state['cmdval'] = 0

		self._setstate()

		logging.debug("%s::: Stop state." % self.name)

		if prev:		
			return False
		else:
			return True

	def setPause(self):
		"""
		Enable Pause mode and set flags.
		Return boolean to indicate state change.
		"""
		prev = self._state['pause']
		self._state['run']   = False
		self._state['stop']  = False
		self._state['pause'] = True
		self._state['init']  = False
		self._state['cmdval'] = 1
		
		self._setstate()
		
		logging.debug("%s::: Pause state." % self.name)
		
		if prev:
			return False
		else:
			return True		

	def setInit(self):
		"""
		Enable Init mode and set flags.
		Return boolean to indicate state change.
		"""
		prev = self._state['init']
		self._state['run']   = False
		self._state['stop']  = False
		self._state['pause'] = False
		self._state['init']  = True
		self._state['cmdval'] = 2

		self._setstate()

		logging.debug("%s::: Init state." % self.name)

		if prev:
			return False
		else:
			return True
	

	def run(self):
		"""
		Run first the internal functionalities, and then calls the user defined runJob method.
		"""
		
		###	Run the internal functionalities	
		
		if self._state['stop']:
			return

		if self._state['pause']:
			return
		
		if self._eventEnd.is_set():
			self._endoam()
			return

		if self._eventDayEnd.is_set():
			self._enddayoam()
			return


		if self._state['init']:
			self._initclass()
							
		if self._eventErr.is_set():	
	
			### Error was detected
			logging.info("%s::: eventErr is set!" % self.name)
	
			### Try to reset  and clear the self._eventErr
			# after self._eventErrdelay time of failed access/run attempts
			if (time.time() - self._eventErrtime) > self._eventErrdelay:
				self._initclass()	
				
			else:	
				self._eventErrcount += 1
				logging.debug("%s::: eventErr was set at %s!" % (self.name, time.ctime(self._eventErrtime)))
				return
	
		try:
			### Run the user defined method						
			self.jobRun()
				
		except rpiBaseClassError as e:
			if e.errval < 4:
				logging.warning("%s" % e.errmsg)
				self._seteventerr('run()', e.errval)
				pass		
			else:
				logging.error("%s\nExiting!" % e.errmsg, exc_info=True)
				self._seteventerr('run()', 4)
				raise
				
		except RuntimeError as e:
			self._seteventerr('run()',4)
			logging.error("RuntimeError: %s\nExiting!" % str(e), exc_info=True)
			raise
					
		except:
			self._seteventerr('run()',4)
			logging.error("Unhandled Exception: %s\nExiting!" % str(sys.exc_info()), exc_info=True)
			raise
												
		finally:
			self._setstate()		


	def restUpdate(self, stream_value):
		"""
		REST API wrapper method to update feed/status value.
		The actual REST call is not performed here! 			
		"""
		if self._restapi is not None:
			self._restapi.setfield(self._restapi_fieldid, stream_value)
			if stream_value < 0:
				self._restapi.setfield('status', "%sError %d at %s" % (self.name, stream_value, time.ctime(self._eventErrtime)))
									

				
	#
	# Private
	#												

	def _initclass(self):
		""""
		(re)Initialize the class.
		"""

		logging.info("%s::: Intialize class" % self.name) 
								
		### User defined init	
		try:
			self.initClass()		
			
		except rpiBaseClassError as e:
			if e.errval < 4:
				logging.warning("%s" % e.errmsg)
				self._seteventerr('_initclass()', e.errval)
				pass		
			else:
				logging.error("%s" % e.errmsg)
				self._seteventerr('_initclass()', 4)
				raise

		except RuntimeError as e:
			self._seteventerr('_initclass()',4)
			logging.error("RuntimeError: %s! Exiting!" % str(e), exc_info=True)
			raise
																														
		except:
			logging.error("Unhandled Exception: %s! Exiting!" % str(sys.exc_info()), exc_info=True)			
			self._seteventerr('_initclass()', 4)
			raise
		
		### Init error event and state
		self._cleareventerr("initClass()")
		self._state['errval'] = 0		

		### Enable Run mode
		self.cmdRun()
		
		
	def _enddayoam(self):
		"""
		End-of-Day OAM procedure.
		"""	

		logging.info("%s::: EoD maintenance sequence run" % self.name) 
			
		### Execute only if eventErr is not set	
		if not self._eventErr.is_set():	
		
			### User defined EoD	
			try:
				self.endDayOAM()																				

			except rpiBaseClassError as e:
				if e.errval < 4:
					logging.warning("%s" % e.errmsg)
					self._seteventerr('_enddayoam()', e.errval)
					pass		
				else:
					logging.error("%s" % e.errmsg)
					self._seteventerr('_enddayoam()', 4)
					raise

			except RuntimeError as e:
				self._seteventerr('_enddayoam()',4)
				logging.error("RuntimeError: %s! Exiting!" % str(e), exc_info=True)
				raise
																														
			except:
				logging.error("Unhandled Exception: %s! Exiting!" % str(sys.exc_info()), exc_info=True)			
				self._seteventerr('_enddayoam()', 4)
				raise
			
			### Init class
			self._initclass()
			
			self._eventDayEnd.clear()
			logging.debug("%s::: Reset eventEndDay" % self.name)

		else:
			logging.debug("%s::: eventErr is set" % self.name)	
	
	
	def _endoam(self):
		"""
		End OAM procedure.
		"""	

		logging.info("%s::: End maintenance sequence run" % self.name) 
		
		### Execute only if eventErr is not set	
		if not self._eventErr.is_set():	
		
			### User defined EoD	
			try:
				self.endOAM()																				

			except rpiBaseClassError as e:
				if e.errval < 4:
					logging.warning("%s" % e.errmsg)
					self._seteventerr('_endoam()', e.errval)
					pass		
				else:
					logging.error("%s" % e.errmsg)
					self._seteventerr('_endoam()', 4)
					raise
		
			except RuntimeError as e:
				self._seteventerr('_endoam()',4)
				logging.error("RuntimeError: %s! Exiting!" % str(e), exc_info=True)
				raise
																									
			except:
				logging.error("Unhandled Exception: %s! Exiting!" % str(sys.exc_info()), exc_info=True)			
				self._seteventerr('_endoam()', 4)
				raise
			
			### Init class
			self._initclass()
			
		else:
			logging.debug("%s::: eventErr is set" % self.name)	
		
		
		
	def _setstate(self):
		"""
		Set the combined/encoded state value corresponding to the cmd and err states.
		"""
		self.stateVal = self._state['errval'] + 4*self._state['cmdval']
		
		
	def _seteventerr(self,str_func,err_val=2):
		"""
		Set eventErr, the error value (2,3 or 4) and store timestamp.
		"""	
		self._eventErr.set()
		self._eventErrtime = time.time()		
		self._state['errval'] |= (err_val-1)
		self._setstate()
		self.restUpdate(-1*err_val+1)
		logging.debug("%s::: Set eventErr in %s at %s!" % (self.name, str_func, time.ctime(self._eventErrtime)))
	
	def _cleareventerr(self,str_func):
		"""
		Clear eventErr and set delay.
		"""	
		if self._eventErr.is_set():
			self._eventErr.clear()
			self._eventErrtime = 0
			self._eventErrdelay = 3*self._config['interval_sec']		
			self._state['errval'] = 0
			self._setstate()		
			self.restUpdate(0)
			logging.debug("%s::: Clear eventErr in %s!" % (self.name, str_func))
