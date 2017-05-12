# -*- coding: utf-8 -*-
"""
    Time-lapse with Rasberry Pi controlled camera
    Copyright (C) 2016-2017 Istvan Z. Kovacs

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

Implements the Events class as group of events to be used in the rpi job.
"""
from threading import Event
from threading import BoundedSemaphore

class rpiEventsClass:
    """
    Implements the Events class: events and variables to be used in all rpi jobs/threads.
    """
    def __init__(self, event_ids):
        self.event_ids    = event_ids

        self.eventErrList       = {}
        self.eventErrtimeList   = {}
        self.eventErrcountList  = {}
        self.eventRuncountList  = {}
        self.stateValList       = {}
        for k, id in self.event_ids.items():
            self.eventErrList[id] = Event()
            self.eventErrList[id].clear()
            self.eventErrtimeList[id]  = 0
            self.eventErrcountList[id] = 0
            self.eventRuncountList[id] = 0
            self.stateValList[id]      = 0

        self.jobRuncount = 0
        self.eventAllJobsEnd = Event()
        self.eventAllJobsEnd.clear()

    def clearEvents(self):
        self.eventAllJobsEnd.clear()

    def resetEventsLists(self):
        self.jobRuncount = 0
        for id in self.event_ids:
            self.eventErrList[id].clear()
            self.eventErrtimeList[id]  = 0
            self.eventErrcountList[id] = 0
            self.eventRuncountList[id] = 0
            self.stateValList[id]      = 0

    def __repr__(self):
        return "<%s (event_ids=%s)>" % (self.__class__.__name__, self.event_ids)

    def __str__(self):
        ret_str = "Events: %s, " % self.eventAllJobsEnd.is_set()
        for k, id in self.event_ids.items():
            ret_str = ret_str + "%s:(%d,%d,%d), " % (id, self.eventErrList[id].is_set(), self.eventRuncountList[id], self.eventErrcountList[id])

        return ret_str
