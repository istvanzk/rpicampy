# -*- coding: utf-8 -*-

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
		
			