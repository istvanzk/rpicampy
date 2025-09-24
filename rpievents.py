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

Implements the rpiEvents class as group of events to be used by the rpicam jobs.
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
