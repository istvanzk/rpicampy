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

Implements the rpiBase class to provide the base with common functionalities for all rpi classes.
"""
import sys
import time
from queue import Queue
from threading import Event
from collections import deque
from threading import RLock
import atexit
from threading import Event
from typing import Any, Dict, List, Tuple, Callable
from multiprocessing import Process, TimeoutError
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_ADDED, EVENT_JOB_REMOVED, EVENT_JOB_MAX_INSTANCES

### The rpi(cam)py modules
from rpilogger import rpiLogger

__all__ = ('CMDRUN', 'CMDSTOP', 'CMDPAUSE', 'CMDINIT', 'CMDRESCH', 'CMDEOD', 'CMDEND',
            'ERRCRIT', 'ERRLEV2', 'ERRLEV1', 'ERRLEV0', 'ERRNONE',
            'rpiBaseClassError', 'rpiBaseClass')


# Default job run time interval
INTERVAL_SEC = 10

# Default time interval for the internal cmd processing job
PROCCMD_INTERVAL_SEC = 3

# Command and state values (remote job control, 4 bits)
CMDRUN   = 3
CMDSTOP  = 0
CMDPAUSE = 1
CMDINIT  = 2
CMDRESCH = 4
CMDEOD   = 5
CMDEND   = 6
CMDCUSTOM= 9

# Error values (levels, 4 bits)
ERRCRIT = 4 #Critical error, raise & exit
ERRLEV2 = 3 #Critical error, count and stop job run
ERRLEV1 = 2 #Non critical timout error, pass
ERRLEV0 = 1 #Non critical error, pass
ERRNONE = 0 #No error


JOB_EVENT_HANDLERS: Dict[int, Callable] = {}
def job_event_handler(event_code: int):
    """
    Decorator for registering handler functions for supported job events.
    """
    def decorator(func):
        JOB_EVENT_HANDLERS.update({event_code: func})
        return func
    return decorator

CMD_HANDLERS: Dict[int, Callable] = {}
def cmd_handler(cmd_type: int):
    """
    Decorator for registering handler functions for supported remote commands. 
    """
    def decorator(func):
        CMD_HANDLERS.update({cmd_type: func})
        return func
    return decorator

class rpiBaseClassError(Exception):
    """
    Exception to be raised by a class derived from rpiBaseClass.
    """

    def __init__(self, errstr, errval):
        self.errmsg = "rpiBaseClassError (errstr='%s', errval=%d)" % (errstr, errval)
        self.errstr = errstr
        self.errval = errval

    def __str__(self):
        return self.errmsg

    def __repr__(self):
        return "<%s (errstr='%s', errval=%d)>" % (self.__class__.__name__, self.errstr, self.errval)


class rpiBaseClass:
    """
    Implements the base class for common functionalities.
    """

    def __init__(self, name, rpi_apscheduler, rpi_events, rpi_config, *args, **kwargs):

        # Public

        # Custom name
        self.name: str    = name or "Job"


        # EoD and End OAM events
        self.eventDayEnd: Event = Event()
        self.eventDayEnd.clear()
        self.eventEnd: Event    = Event()
        self.eventEnd.clear()

        # Private

        # Get the custom config parameters
        self._config: Dict = rpi_config

        # Reference to the APScheduler
        self._sched  = rpi_apscheduler or None
        self._sched_lock: RLock = self._create_lock()
 
        # Reference to own entry in eventErr from the rpi_events
        self._eventErr: Event = rpi_events.eventErrList[self.name]
        # Reference to stateValList from the rpi_events and init own entry
        self._stateValList: Dict[str, int] = rpi_events.stateValList
        self._stateValList[self.name] = 0
        self._stateVal = 0

        # Error event related
        self._eventErrdelay = 0
        self._eventErrcount = 0
        self._eventErrtime  = 0

        # Job start/stop and interval times
        self._dtstart = None
        self._dtstop  = None
        self._interval_sec = INTERVAL_SEC

        # The commands and requuests queues, check/process interval, job name
        self._cmds: Queue = Queue(10)
        self._reqs: Queue = Queue(10)
        self._proc_cmdreq_interval_sec = PROCCMD_INTERVAL_SEC
        self._proc_cmdreq_name: str = "%s_CmdReq_%d" % (self.name, self._proc_cmdreq_interval_sec)

        # The state flags and state/cmd value codes
        self._state: Dict    = dict()
        self._state['run']   = False
        self._state['stop']  = False
        self._state['pause'] = False
        self._state['init']  = False
        self._state['resch'] = False
        self._state['cmdval'] = 0
        self._state['errval'] = 0
        self._state_lock: RLock = self._create_lock()

        # The last 10 status messages
        self._statusmsg: deque = deque([],10)

        # ATExit handler
        atexit.register(self._clean_exit)

        # Init class
        self._initclass()

    def __repr__(self):
        return "<%s (name=%s, rpi_apscheduler=%s, rpi_events=dict())>" % (self.__class__.__name__, self._sched, self.name)

    def __str__(self):
        return "rpibase for %s::: Cmd(tstart_per:%s, tstop_per:%s, interval_sec=%d), eventErr(count: %d, time: %s, delay: %s), state: %s, stateVal: %d, cmds: %s, reqs: %s, statusmsg: %s" % \
            (self.name, self._dtstart, self._dtstop, self._interval_sec, self._eventErrcount, time.ctime(self._eventErrtime), self._eventErrdelay, self._state, self._stateVal, self._cmds, self._reqs, self._statusmsg)

    def __del__(self):
        if self._sched is not None:
            with self._sched_lock:
                if self._sched.get_job(self._proc_cmdreq_name) is not None:
                    self._sched.remove_job(self._proc_cmdreq_name)
                if self._sched.get_job(self.name) is not None:
                    self._sched.remove_job(self.name)

        rpiLogger.debug("rpibase for %s::: Deleted!", self.name)
        self._statusmsg.append((f"{self.name} Deleted", ERRNONE))

    #
    # Subclass interface methods to be overriden by user defined methods.
    #
    def jobRun(self):
        """
        Main function. 
        To be overriden by user defined method.
        """
        pass

    def initClass(self):
        """"
        (re)Initialize the class. 
        To be overriden by user defined method.
        """
        pass

    def endDayOAM(self):
        """"
        End-Of-Day OAM. 
        To be overriden by user defined method.
        """
        pass

    def endOAM(self):
        """"
        End OAM. 
        To be overriden by user defined method.
        """
        pass

    def procCustomReq(self, reqstr:str):
        """
        Process a custom request with arguments in reqstr.
        To be overriden by user defined method.
        """
        pass

    def procCustomCmd(self, cmdstr:str):
        """
        Process a custom command with arguments in cmdstr.
        To be overriden by user defined method.
        """
        pass

    @job_event_handler(EVENT_JOB_EXECUTED)
    def handleJobExecuted(self):
        """
        Handle the job executed event.
        The registered handler function should be decorated with @rpibase.job_event_handler(EVENT_JOB_EXECUTED).
        """
        pass

    @job_event_handler(EVENT_JOB_MAX_INSTANCES)
    def handleJobMaxInstances(self):
        """
        Handle the job max instances event.
        The registered handler function should be decorated with @rpibase.job_event_handler(EVENT_JOB_MAX_INSTANCES).
        """
        pass

    @job_event_handler(EVENT_JOB_ERROR)
    def handleJobError(self):
        """
        Handle the job error event.
        The registered handler function should be decorated with @rpibase.job_event_handler(EVENT_JOB_ERROR).
        """
        pass

    @job_event_handler(EVENT_JOB_ADDED)
    def handleJobAdded(self):
        """
        Handle the job added event.
        The registered handler function should be decorated with @rpibase.job_event_handler(EVENT_JOB_ADDED).
        """
        pass

    @job_event_handler(EVENT_JOB_REMOVED)
    def handleJobRemoved(self):
        """
        Handle the job removed event.
        The registered handler function should be decorated with @rpibase.job_event_handler(EVENT_JOB_REMOVED).
        """
        pass



    #
    # Subclass interface methods to be used externally. NO overriding by user defined methods!
    #
    def handleJobEvent(self, event_code: Any | None = ERRNONE):
        """
        Handle the job event and call the registered handler functions.
        The registered handler functions should be decorated with @job_event_handler(event_code).
        """
        if event_code in JOB_EVENT_HANDLERS:
            JOB_EVENT_HANDLERS[event_code](self)
        else:
            rpiLogger.warning("rpibase for %s::: No handler registered for job event code %d", self.name, event_code)

    def manualRun(self, ch):
        """
        Trigger the execution of the job just as it would be executed by the scheduler.
        """
        #rpiLogger.info(f"{self.name}::: Waiting for RLock to execute Manual trigger")
        #with self._sched_lock:
        #   rpiLogger.info(f"{self.name}::: Execute Manual trigger")
        self._run()


    def queueCmd(self, cmdrx_tuple) -> bool:
        """
        Puts a remote command (tuple) in the cmd queue.
        Returns boolean to indicate success status.
        """

        if self._cmds.full():
            self._seteventerr('queueCmd()',ERRLEV0)
            rpiLogger.warning("rpibase for %s::: Cmd queue is full: %s", self.name, self._cmds)
            return False

        self._cmds.put(cmdrx_tuple, True, 5)
        return True

    def queueReq(self, reqrx_tuple) -> bool:
        """
        Puts a request (tuple) in the req queue.
        Returns boolean to indicate success status.
        """

        if self._reqs.full():
            self._seteventerr('queueCmd()',ERRLEV0)
            rpiLogger.warning("rpibase for %s::: Req queue is full: %s", self.name, self._reqs)
            return False

        self._reqs.put(reqrx_tuple, True, 5)
        return True

    def setInit(self) -> bool:
        """
        Run Init mode and set flags.
        Return boolean to indicate state change.
        """
        if self._state['init'] or self.eventDayEnd.is_set() or self.eventEnd.is_set():
            rpiLogger.debug("rpibase for %s::: %s: _initclass not run", self.name, sys._getframe().f_code.co_filename)
            return False
        else:
            self._initclass()
            return True

    @cmd_handler(CMDRUN)
    def setRun(self, tstartstopintv=None) -> bool:
        """
        Run Run mode and set flags.
        When the tstartstopintv=(start, stop, interval) tuple is specified (re)configure and add self._run() job to the scheduler.
        Return boolean to indicate state change.
        """
        if self._state['run'] or self.eventDayEnd.is_set() or self.eventEnd.is_set():
            rpiLogger.debug("rpibase for %s::: %s: add/resume_run not run", self.name, sys._getframe().f_code.co_filename)
            return False
        else:
            if tstartstopintv is not None:
                self.timePeriodIntv = tstartstopintv
                self._remove_run()
                self._add_run()
            else:
                self._resume_run()
            return True

    @cmd_handler(CMDSTOP)
    def setStop(self) -> bool:
        """
        Run Stop mode and set flags.
        Return boolean to indicate state change.
        """
        if self._state['stop'] or self.eventDayEnd.is_set() or self.eventEnd.is_set():
            rpiLogger.debug("rpibase for %s::: %s: _remove_run not run", self.name, sys._getframe().f_code.co_filename)
            return False
        else:
            self._remove_run()
            return True

    @cmd_handler(CMDSTOP)
    def setPause(self) -> bool:
        """
        Run Pause mode and set flags.
        Return boolean to indicate state change.
        """
        if self._state['pause'] or self.eventDayEnd.is_set() or self.eventEnd.is_set():
            rpiLogger.debug("rpibase for %s::: %s: _pause_run not run", self.name, sys._getframe().f_code.co_filename)
            return False
        else:
            self._pause_run()
            return True

    @cmd_handler(CMDRESCH)
    def setResch(self, tstartstopintv=None) -> bool:
        """
        Run Re-schedule mode and set flags.
        When the tstartstopintv=(start, stop, interval) tuple is specified (re)configure.
        Return boolean to indicate state change.
        """
        if self._state['resch'] or self.eventDayEnd.is_set() or self.eventEnd.is_set():
            return False
        else:
            if tstartstopintv is not None:
                self.timePeriodIntv = tstartstopintv
            self._reschedule_run()
            return True

    @cmd_handler(CMDEOD)
    def setEndDayOAM(self) -> bool:
        """
        Run End-of-Day OAM mode and set flags.
        Return boolean to indicate state change.
        """
        if self._state['run'] or self._state['pause'] or self._state['resch'] or \
            self.eventDayEnd.is_set() or self.eventEnd.is_set():
            rpiLogger.debug("rpibase for %s::: %s: _enddayoam_run not run", self.name, sys._getframe().f_code.co_filename)
            return False
        else:
            self._enddayoam_run()
            return True

    @cmd_handler(CMDEND)
    def setEndOAM(self) -> bool:
        """
        Run End OAM mode and set flags.
        Return boolean to indicate state change.
        """
        if self._state['run'] or self._state['pause'] or self._state['resch'] or \
            self.eventDayEnd.is_set() or self.eventEnd.is_set():
            rpiLogger.debug("rpibase for %s::: %s: _endoam_run not run", self.name, sys._getframe().f_code.co_filename)
            return False
        else:
            self._endoam_run()
            return True


    @property
    def statusUpdate(self):
        """
        Get the last status message (tuple) in the deque.
        """
        try:
            str, val  = self._statusmsg.pop()
            return str, val
        except IndexError as e:
            return None, ERRNONE


    @statusUpdate.setter
    def statusUpdate(self, status_tuple):
        """
        Update status message (tuple) in the deque.
        """
        #message_str=None, message_value=ERRNONE
        #(message_str, message_value)
        self._statusmsg.append(status_tuple)

    @property
    def timePeriodIntv(self):
        """
        Get the start and stop datetime and interval seconds values as a tuple.
        """
        return (self._dtstart, self._dtstop, self._interval_sec)

    @timePeriodIntv.setter
    def timePeriodIntv(self, tstartstopintv):
        """
        Set the start and stop datetime and interval seconds values.
        """
        self._dtstart    = tstartstopintv[0]
        self._dtstop     = tstartstopintv[1]
        self._interval_sec  = tstartstopintv[2]

    @property
    def errorDelay(self):
        """
        Return the allowed time delay (grace period) before re-initializing the class after a fatal error.
        """
        return self._eventErrdelay

    @errorDelay.setter
    def errorDelay(self, delay_sec):
        """
        Set the allowed time delay (grace period) before re-initializing the class after a fatal error.
        """
        self._eventErrdelay = delay_sec

    @property
    def errorTime(self):
        """
        Return the time (time.time()) when the last error was set.
        """
        return self._eventErrtime

    @property
    def errorLevel(self):
        """
        Return the current error level (ERRLEV0, ERRLEV1, ERRLEV2 or ERRCRIT).
        """
        return self._state['errval']

    @property
    def errorCount(self):
        """
        Return the number of times the job has run while in the delay time period (self._eventErrcount).
        """
        return self._eventErrcount

    @property
    def stateValue(self):
        """
        Return the combined/encoded state value corresponding to the cmd and err states.
        """
        self._setstateval()
        return self._stateVal



    #
    # Private
    #

    def _run(self):
        """
        Run first the internal functionalities, and then call the user defined runJob method in a Process.
        Catch all rpiBaseClassError exceptions such that the job executor can handle the error events and logging.
        """
        try:
            # Set Run state
            self._run_state()

            # Run the user defined method
            # Launches the job in a separate process and enforces a timeout.
            p = Process(target=self.jobRun)
            p.start()
            p.join(timeout=0.8*self._interval_sec)
            if p.is_alive():
                self._seteventerr('_run()', ERRLEV1)
                p.terminate()
                p.join(timeout=0.1*self._interval_sec)
                rpiLogger.warning("rpibase for %s::: jobRun processs timed out and was terminated", self.name)
            else:
                self._cleareventerr('_run()')

        except rpiBaseClassError as e:
            # Route exceptions to the appropriate error level handling and logging.
            # The user defined jobRun() and related methods should raise rpiBaseClassError exceptions with the appropriate error level.
            # The user defined handleJobError() and handleJobExecuted() methods can be used to handle the events, in a job specific manner.
            if  e.errval > ERRNONE:
                if e.errval < ERRLEV2:
                    # Can be handled by the user defined handleJobExecuted() method
                    self._seteventerr('_run()', e.errval)
                    rpiLogger.warning("rpibase for %s::: eventErr %d: %s", self.name, self._state['errval'], e.errmsg)
                    pass
                else:
                    # Can be handled by the user defined handleJobError() method
                    self._seteventerr('_run()', ERRCRIT)
                    rpiLogger.exception("rpibase for %s::: eventErr %d: %s\nExiting job!", self.name, self._state['errval'], e.errmsg)
                    raise
            else:
                self._seteventerr('_run()', ERRNONE)
                rpiLogger.warning("rpibase for %s::: eventErr %d: A non-error was raised: %s", self.name, self._state['errval'], e.errmsg)
                pass

        except RuntimeError as e:
            # Can be handled by the user defined handleJobError() method
            self._seteventerr('_run()',ERRCRIT)
            rpiLogger.exception("rpibase for %s::: RuntimeError: \nExiting job!", self.name)
            raise

        except TimeoutError as e:
            # Can be handled by the user defined handleJobExecuted() method
            self._seteventerr('_run()',ERRLEV1)
            rpiLogger.warning("rpibase for %s::: jobRun process timed out and was terminated", self.name)
            pass

        except:
            # Can be handled by the user defined handleJobError() method
            self._seteventerr('_run()',ERRCRIT)
            rpiLogger.exception("rpibase for %s::: Unhandled Exception: \nExiting job!", self.name)
            raise

        finally:
            self._setstateval()


    def _initclass(self):
        """"
        (re)Initialize some of the class attributes related to the job state and error events.
        Do not schedule the self._run() job here, it is done in the setRun() method.
        """

        rpiLogger.info("rpibase for %s::: Initialize class", self.name)

        ### Stop and remove the self._run()  and self._proc_cmdreq() jobs from the scheduler
        self._remove_run()
        if self._sched is not None:
            with self._sched_lock:
                if self._sched.get_job(self._proc_cmdreq_name) is not None:
                    self._sched.remove_job(self._proc_cmdreq_name)

        ### Empty the cmd queue
        while not self._cmds.empty():
            (cmdstr,cmdval) = self._cmds.get()
            self._cmds.task_done()

        ### Empty the status message queue
        self._statusmsg.clear()

        ### Init error event and state
        self._cleareventerr('_initclass()')
        self._state['errval'] = ERRNONE

        ### Clear other events
        self.eventDayEnd.clear()
        self.eventEnd.clear()

        ### Add the self._proc_cmdreq() job to the scheduler
        if self._sched is not None:
            with self._sched_lock:
                self._sched.add_job(self._proc_cmdreq, trigger='interval', id=self._proc_cmdreq_name , seconds=self._proc_cmdreq_interval_sec, misfire_grace_time=5, name=self._proc_cmdreq_name )

        ### Set Init state
        self._init_state()


    def _proc_cmdreq(self):
        """
        If the Job is not scheduled, set the Stop state.
        Process and act upon received commands.
        Process and act upon received requests.
        """
        # Set the Stop state if the Job is not scheduled
        if self._sched is not None:
            with self._sched_lock:
                if not self._state['stop'] and self._sched.get_job(self.name) is None:
                    self._stop_state()

        # Process and act upon received (enqueued) commands and requests
        self._proc_cmd()
        self._proc_req()

    def _proc_cmd(self):
        """
        Process and act upon received commands.
        """
        if self._cmds.empty():
            rpiLogger.debug("rpibase for %s::: _proc_cmd: Cmd queue is empty!", self.name)
            return

        if (not self.eventDayEnd.is_set()) and (not self.eventEnd.is_set()):

            # Get a command
            (cmdstr, cmdval) = self._cmds.get()

            rpiLogger.debug("rpibase for %s::: _proc_cmd: Get cmdstr:%s, cmdval:%d", self.name, cmdstr, cmdval)

            if cmdval != CMDCUSTOM and CMD_HANDLERS[cmdval]():
                self._statusmsg.append(("cmd %s" % CMD_HANDLERS[cmdval].__name__, ERRNONE))

            elif cmdval == CMDCUSTOM:
                self.procCustomCmd(cmdstr)
                self._statusmsg.append(("cmd procCustomCmd(%s)" % cmdstr, ERRNONE))
                
            self._cmds.task_done()

    def _proc_req(self):
        """
        Process and act upon received requests.
        """
        if self._reqs.empty():
            rpiLogger.debug("rpibase for %s::: _proc_req: Req queue is empty!", self.name)
            return

        if (not self.eventDayEnd.is_set()) and (not self.eventEnd.is_set()):

            # Get a command
            (reqstr, reqval) = self._reqs.get()

            rpiLogger.debug("rpibase for %s::: _proc_req: Get reqstr:%s, reqval:%d", self.name, reqstr, reqval)

            if reqval:
                self.procCustomReq(reqstr)
                self._statusmsg.append(("cmd procCustomReq(%s)" % reqstr, ERRNONE))

            self._reqs.task_done()

    def _setstateval(self):
        """
        Set the combined/encoded state value corresponding to the cmd and err states (8bits):
        job error state in lower 4 bits
        job cmd state in upper 4 bits
        """
        if self._sched is not None:
            with self._state_lock:
                self._stateVal = self._state['errval'] + 16*self._state['cmdval']
                self._stateValList[self.name] = self._stateVal


    def _seteventerr(self,str_func,err_val=ERRLEV0):
        """
        Set eventErr, set the error value (ERRLEV0, ERRLEV1, ERRLEV2 or ERRCRIT) and store timestamp.
        """
        if err_val > ERRNONE:
            str = "%s: %s SetError %d" % (self.name, str_func, err_val)
            self._statusmsg.append((str, -1*err_val))
            self._eventErr.set()
            self._eventErrtime = time.time()
            self._state['errval'] = err_val
            self._setstateval()
            rpiLogger.debug("rpibase for %s::: Set eventErr %d in %s at %s!", self.name, err_val, str_func, time.ctime(self._eventErrtime))

    def _cleareventerr(self,str_func):
        """
        Clear eventErr and reset error value and reset timestamp.
        """
        str = "%s: %s ClrError %d" % (self.name, str_func, self._state['errval'])
        self._statusmsg.append((str, ERRNONE))
        rpiLogger.debug("rpibase for %s::: Clear eventErr %d in %s!", self.name, self._state['errval'], str_func)
        self._eventErr.clear()
        self._eventErrtime = 0
        self._state['errval'] = ERRNONE
        self._setstateval()


    def _add_run(self):
        """
        Add the self._run() method as a job in the APScheduler.
        """
        if self._sched is not None:
            with self._sched_lock:
                if self._sched.get_job(self.name) is None:
                    self._add_job()
                else:
                    self._reschedule_run()

        self._run_state()

    def _add_job(self):
        """ 
        Schedule/add the self._run() job depending on the specified start/stop times. 
        """
        if self._dtstart is not None:
            if self._dtstop is not None:
                self._sched.add_job(self._run, 
                                    trigger='interval', 
                                    id=self.name, 
                                    seconds=self._interval_sec, 
                                    start_date=self._dtstart, 
                                    end_date=self._dtstop, 
                                    name=self.name )
            else:
                self._sched.add_job(self._run, 
                                    trigger='interval',
                                    id=self.name,
                                    seconds=self._interval_sec,
                                    start_date=self._dtstart,
                                    name=self.name )
        else: 
            if self._dtstop is not None:
                self._sched.add_job(self._run, 
                                    trigger='interval',
                                    id=self.name,
                                    seconds=self._interval_sec,
                                    end_date=self._dtstop,
                                    name=self.name )
            else:
                self._sched.add_job(self._run,
                                    trigger='interval',
                                    id=self.name,
                                    seconds=self._interval_sec,
                                    name=self.name )


    def _init_state(self):
        """
        Set Init state for the scheduled self._run() job.
        """
        self._state['run']   = False
        self._state['stop']  = False
        self._state['pause'] = False
        self._state['init']  = True
        self._state['resch'] = False
        self._state['cmdval'] = CMDINIT

        self._setstateval()

        rpiLogger.debug("rpibase for %s::: Init state.", self.name)

    def _run_state(self):
        """
        Set Run state for the scheduled self._run() job.
        """
        self._state['run']   = True
        self._state['stop']  = False
        self._state['pause'] = False
        self._state['init']  = False
        self._state['resch'] = False
        self._state['cmdval'] = CMDRUN

        self._setstateval()

        rpiLogger.debug("rpibase for %s::: Run state.", self.name)

    def _pause_state(self):

        self._state['run']   = False
        self._state['stop']  = False
        self._state['pause'] = True
        self._state['init']  = False
        self._state['resch'] = False
        self._state['cmdval'] = CMDPAUSE

        self._setstateval()

        rpiLogger.debug("rpibase for %s::: Pause state.", self.name)

    def _stop_state(self):
        """
        Set Stop state for the scheduled self._run() job.
        """
        self._state['run']   = False
        self._state['stop']  = True
        self._state['pause'] = False
        self._state['init']  = False
        self._state['resch'] = False
        self._state['cmdval'] = CMDSTOP

        self._setstateval()

        rpiLogger.debug("rpibase for %s::: Stop state.", self.name)

    def _resume_run(self):
        """
        Resume/add the paused or stopped self._run() job.
        Set the Run state.
        """
        if self._sched is not None and (self._state['stop'] or self._state['pause']):
            with self._sched_lock:
                if self._sched.get_job(self.name) is not None:
                    self._sched.resume_job(self.name)
                else:
                    self._add_run()

            self._run_state()

    def _pause_run(self):
        """
        Pause the scheduled self._run() job.
        Set the Pause state.
        """
        if self._sched is not None and not self._state['pause']:
            with self._sched_lock:
                if self._sched.get_job(self.name) is not None:
                    self._sched.pause_job(self.name)

            self._pause_state()

    def _remove_run(self):
        """
        Remove the scheduled self._run() job.
        Set the Stop state.
        """
        if self._sched is not None and not self._state['stop']:
            with self._sched_lock:
                if self._sched.get_job(self.name) is not None:
                    self._sched.remove_job(self.name)

            self._stop_state()

    def _reschedule_run(self):
        """
        Re-schedule the self._run() job.
        Set the ReScheduled state.
        """
        if self._sched is not None and not self._state['resch']:
            with self._sched_lock:
                if self._sched.get_job(self.name) is not None:
                    self._reschedule_job()

        self._state['run']   = False
        self._state['stop']  = False
        self._state['pause'] = False
        self._state['init']  = False
        self._state['resch'] = True
        self._state['cmdval'] = CMDRESCH

        self._setstateval()

        rpiLogger.debug("rpibase for %s::: Rescheduled state." % self.name)

    def _reschedule_job(self):
        """ 
        Re-schedule the self._run() job depending on the specified start/stop times. 
        """
        if self._dtstart is not None:
            if self._dtstop is not None:
                self._sched.reschedule_job(self.name,
                                            trigger='interval',
                                            seconds=self._interval_sec,
                                            start_date=self._dtstart,
                                            end_date=self._dtstop,
                                            name=self.name )
            else:
                self._sched.reschedule_job(self.name,
                                            trigger='interval',
                                            seconds=self._interval_sec,
                                            start_date=self._dtstart,
                                            name=self.name )
        else: 
            if self._dtstop is not None:
                self._sched.reschedule_job(self.name,
                                           trigger='interval',
                                           seconds=self._interval_sec,
                                           end_date=self._dtstop,
                                           name=self.name )
            else:
                self._sched.reschedule_job(self.name,
                                           trigger='interval',
                                           seconds=self._interval_sec,
                                           name=self.name )


    def _enddayoam_run(self):
        """
        End-of-Day OAM procedure.
        """

        ### Execute only if eventErr is not set
        if not self._eventErr.is_set():

            ### Set the event
            self.eventDayEnd.set()

            ### User defined EoD
            self.endDayOAM()

            rpiLogger.info("rpibase for %s::: endDayOAM(): Maintenance sequence run", self.name)

            ### Clear the event
            self.eventDayEnd.clear()

        else:
            rpiLogger.debug("rpibase for %s::: _enddayoam(): eventErr is set", self.name)


    def _endoam_run(self):
        """
        End OAM procedure.
        """

        ### Execute only if eventErr is not set
        if not self._eventErr.is_set():

            ### Set the event
            self.eventEnd.set()

            ### User defined EoD
            self.endOAM()

            rpiLogger.info("rpibase for %s::: endOAM(): Maintenance sequence run", self.name)

            ### Clear the event
            self.eventEnd.clear()

        else:
            rpiLogger.debug("rpibase for %s::: _endoam(): eventErr is set", self.name)


    def _create_lock(self) -> RLock:
        """
        Creates a reentrant lock object.
        """
        return RLock()

    def _clean_exit(self):
        """
        An atexit handler for the current job.
        Stop and remove the self._run()  and self._proc_cmdreq() jobs from the scheduler.
        """
        rpiLogger.warning("rpibase for %s::: The job is exiting!", self.name)

        self._remove_run()
        
        if self._sched is not None:
            with self._sched_lock:
                if self._sched.get_job(self._proc_cmdreq_name) is not None:
                    self._sched.remove_job(self._proc_cmdreq_name)

        rpiLogger.debug("rpibase for %s::: Exit!", self.name)
        self._statusmsg.append((f"{self.name} Exit", ERRNONE))
