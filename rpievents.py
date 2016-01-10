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
 
Implements the Events class (group of events to be used in the rpi threads)
    
"""    
from threading import Event
from threading import BoundedSemaphore

class rpiEventsClass():
	"""
	Implements the Events class (group of events to be used in the rpi threads)
	"""
	def __init__(self, event_ids):
		self.event_ids    = event_ids
		
		self.eventErrList 		= {}
		self.eventErrtimeList 	= {}
		self.eventErrdelayList	= {}
		self.eventErrcountList	= {}
		self.eventRuncountList	= {}
		for id in self.event_ids:
			self.eventErrList[id] = Event() 
			self.eventErrList[id].clear()			
			self.eventErrtimeList[id]  = 0 
			self.eventErrdelayList[id] = 0 
			self.eventErrcountList[id] = 0 
			self.eventRuncountList[id] = 0 
			
		self.jobRuncount = 0
			
		self.eventDayEnd = Event()
		self.eventEnd    = Event()
		self.eventDayEnd.clear()
		self.eventEnd.clear()
		
		self.EventSema = BoundedSemaphore()
		
	def acquireSemaphore(self):
		self.SemaEvent.acquire()
		
	def releaseSemaphore(self):
		self.SemaEvent.release()		

	def clearEvents(self):
		self.eventDayEnd.clear()
		self.eventEnd.clear()
		for id in self.event_ids:
			self.eventErrList[id].clear()			
			self.eventErrtimeList[id]  = 0 
			self.eventErrdelayList[id] = 0 
			self.eventErrcountList[id] = 0 
	
	def resetEventsLists(self):
		self.jobRuncount = 0	
		for id in self.event_ids:
			self.eventErrtimeList[id]  = 0 
			self.eventErrdelayList[id] = 0 
			self.eventErrcountList[id] = 0 
			self.eventRuncountList[id] = 0 
	
	def __str__(self):
		ret_str = "Events: "
		for id in self.event_ids:
			ret_str = ret_str + ("%sErr:%d,%d,%d " % (id, self.eventErrList[id].is_set(), self.eventRuncountList[id], self.eventErrcountList[id]))
		
		ret_str = ret_str + ("DayEnd:%d, End:%d" % (self.eventDayEnd.is_set(), self.eventEnd.is_set()))	
			
		return ret_str	
			
	def __del__(self):
		for id in self.event_ids:
			self.eventErrList[id].clear()			
	
		self.eventDayEnd.set()
		self.eventEnd.set()
		
			