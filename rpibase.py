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

Implements the rpiBase class to provide the base with common functionalities for all rpi classes.
"""
import sys
import time
from queue import Queue
from threading import Event
from collections import deque
from threading import RLock
import atexit

### The rpi(cam)py modules
from rpilogger import rpiLogger

__all__ = ('CMDRUN', 'CMDSTOP', 'CMDPAUSE', 'CMDINIT', 'CMDRESCH', 'CMDEOD', 'CMDEND',
            'ERRCRIT', 'ERRLEV2', 'ERRLEV1', 'ERRLEV0', 'ERRNONE',
            'rpiBaseClassError', 'rpiBaseClass',
            'initClass', 'jobRun', 'endDayOAM', 'endOAM',
            'queueCmd', 'setInit', 'setRun', 'setStop', 'setPause', 'setResch', 'setEndDayOAM', 'setEndOAM',
            'statusUpdate', 'errorDelay', 'timerPeriodIntv', 'errorTime', 'errorCount', 'errorDelay', 'stateValue')

# Command and state values (remote job control, 4 bits)
CMDRUN   = 3
CMDSTOP  = 0
CMDPAUSE = 1
CMDINIT  = 2
CMDRESCH = 4
CMDEOD   = 5
CMDEND   = 6

# Error values (levels, 4 bits)
ERRCRIT = 4 #Critical error, raise & exit
ERRLEV2 = 3 #Non critical error, pass
ERRLEV1 = 2 #Non critical error, pass
ERRLEV0 = 1 #Non critical error, pass
ERRNONE = 0 #No error


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

    def __init__(self, name, rpi_apscheduler, rpi_events):

        # Public

        # Custom name
        self.name    = name or "Job"

        # EoD and End OAM events
        self.eventDayEnd = Event()
        self.eventDayEnd.clear()
        self.eventEnd    = Event()
        self.eventEnd.clear()

        # Private

        # Reference to the APScheduler
        self._sched  = rpi_apscheduler or None
        self._sched_lock = self._create_lock()
 
        # Reference to eventErr (can be accessed via the rpi_events)
        self._eventErr      = rpi_events.eventErrList[self.name]

        # Error event related
        self._eventErrdelay = 0
        self._eventErrcount = 0
        self._eventErrtime  = 0

        # Job start/stop and interval times
        self._dtstart = None
        self._dtstop  = None
        self._interval_sec = 13

        # The commands queue, check/process interval, job name
        self._cmds = Queue(10)
        self._proccmd_interval_sec = 11
        self._cmdname = "%s_Cmd%d" % (self.name, self._proccmd_interval_sec)

        # The state flags and state/cmd value codes
        self._state          = {}
        self._state['run']   = False
        self._state['stop']  = False
        self._state['pause'] = False
        self._state['init']  = False
        self._state['resch'] = False
        self._state['cmdval'] = -1
        self._state['errval'] = 0
        self._stateVal       = 0
        self._state_lock = self._create_lock()

        # The last 10 status messages
        self._statusmsg = deque([],10)

        # ATExit handler
        atexit.register(self._clean_exit)

        # Init class
        self._initclass()

    def __repr__(self):
        return "<%s (name=%s, rpi_apscheduler=%s, rpi_events=dict())>" % (self.__class__.__name__, self._sched, self.name)

    def __str__(self):
        return "%s::: Cmd(tstart_per:%s, tstop_per:%s, interval_sec=%d), eventErr(count: %d, time: %s, delay: %s), state: %s, stateVal: %d, cmds: %s, statusmsg: %s" % \
            (self.name, self._dtstart, self._dtstop, self._interval_sec, self._eventErrcount, time.ctime(self._eventErrtime), self._eventErrdelay, self._state, self._stateVal, self._cmds, self._statusmsg)

    def __del__(self):
        if self._sched is not None:
            with self._sched_lock:
                if self._sched.get_job(self._cmdname) is not None:
                    self._sched.remove_job(self._cmdname)
                if self._sched.get_job(self.name) is not None:
                    self._sched.remove_job(self.name)

        rpiLogger.debug("%s::: Deleted!" % self.name)
        self._statusmsg.append(("%s Deleted" % self.name, ERRNONE))

    #
    # Subclass interface methods to be overriden by user defined methods.
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
    # Subclass interface methods to be used externally.
    #

    def manualRun(self, ch):
        """
        Trigger the execution of the job just as it would be executed by the scheduler
        """
        #rpiLogger.info(f"{self.name}::: Waiting for RLock to execute Manual trigger")
        #with self._sched_lock:
        #   rpiLogger.info(f"{self.name}::: Execute Manual trigger")
        self._run()


    def queueCmd(self, cmdrx_tuple):
        """
        Puts a remote command (tuple) in the cmd queue.
        Returns boolean to indicate success status.
        """

        if self._cmds.full():
            self._seteventerr('queueCmd()',ERRLEV0)
            rpiLogger.warning("%s::: Cmd queue is full: %s" % (self.name, self._cmds))
            return False

        self._cmds.put(cmdrx_tuple, True, 5)
        return True

    def setInit(self):
        """
        Run Init mode and set flags.
        Return boolean to indicate state change.
        """
        if self._state['init'] or self.eventDayEnd.is_set() or self.eventEnd.is_set():
            rpiLogger.debug("%s::: %s: _initclass not run" % (self.name, sys._getframe().f_code.co_filename))
            return False
        else:
            self._initclass()
            return True

    def setRun(self, tstartstopintv=None):
        """
        Run Run mode and set flags.
        When the tstartstopintv=(start, stop, interval) tuple is specified (re)configure and add self._run() job to the scheduler.
        Return boolean to indicate state change.
        """
        if self._state['run'] or self.eventDayEnd.is_set() or self.eventEnd.is_set():
            rpiLogger.debug("%s::: %s: add/resume_run not run" % (self.name, sys._getframe().f_code.co_filename))
            return False
        else:
            if tstartstopintv is not None:
                self.timePeriodIntv = tstartstopintv
                self._remove_run()
                self._add_run()
            else:
                self._resume_run()
            return True

    def setStop(self):
        """
        Run Stop mode and set flags.
        Return boolean to indicate state change.
        """
        if self._state['stop'] or self.eventDayEnd.is_set() or self.eventEnd.is_set():
            rpiLogger.debug("%s::: %s: _remove_run not run" % (self.name, sys._getframe().f_code.co_filename))
            return False
        else:
            self._remove_run()
            return True

    def setPause(self):
        """
        Run Pause mode and set flags.
        Return boolean to indicate state change.
        """
        if self._state['pause'] or self.eventDayEnd.is_set() or self.eventEnd.is_set():
            rpiLogger.debug("%s::: %s: _pause_run not run" % (self.name, sys._getframe().f_code.co_filename))
            return False
        else:
            self._pause_run()
            return True

    def setResch(self):
        """
        Run Re-schedule mode and set flags.
        Return boolean to indicate state change.
        """
        if self._state['resch'] or self.eventDayEnd.is_set() or self.eventEnd.is_set():
            return False
        else:
            self._reschedule_run()
            return True

    def setEndDayOAM(self):
        """
        Run End-of-Day OAM mode and set flags.
        Return boolean to indicate state change.
        """
        if self._state['run'] or self._state['pause'] or self._state['resch'] or \
            self.eventDayEnd.is_set() or self.eventEnd.is_set():
            rpiLogger.debug("%s::: %s: _enddayoam_run not run" % (self.name, sys._getframe().f_code.co_filename))
            return False
        else:
            self._enddayoam_run()
            return True

    def setEndOAM(self):
        """
        Run End OAM mode and set flags.
        Return boolean to indicate state change.
        """
        if self._state['run'] or self._state['pause'] or self._state['resch'] or \
            self.eventDayEnd.is_set() or self.eventEnd.is_set():
            rpiLogger.debug("%s::: %s: _endoam_run not run" % (self.name, sys._getframe().f_code.co_filename))
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
    def errorCount(self):
        """
        Return the number of times the job has run while in the delay time period (self._eventErrdelay).
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
        Run first the internal functionalities, and then call the user defined runJob method.
        Catch all rpiBaseClassError exceptions.
        """

        ### Run the internal functionalities first then the user defined method (self.jobRun)
        try:
            # Apply re-initialization grace period after a fatal error (ERRCRIT level)
            # Re-initialize the self._run() method
            # after self._eventErrdelay seconds from the last failed access/run attempt
            if self._eventErr.is_set():
                self._eventErrcount += 1
                rpiLogger.info("%s::: eventErr is set (run %d)!" % (self.name, self._eventErrcount))
                if (time.time() - self._eventErrtime) < self._eventErrdelay:
                    rpiLogger.debug("%s::: eventErr was set at %s (run %d)!" % (self.name, time.ctime(self._eventErrtime), self._eventErrcount))
                    return

                self._initclass()
                self._add_run()
                #return

            # Set Run state
            self._run_state()

            # Run the user defined method
            self.jobRun()

        except rpiBaseClassError as e:
            if  e.errval > ERRNONE:
                if e.errval < ERRCRIT:
                    self._seteventerr('_run()', e.errval)
                    rpiLogger.warning("%s" % e.errmsg)
                    pass
                else:
                    self._seteventerr('_run()', ERRCRIT)
                    rpiLogger.error("%s\nExiting job!" % e.errmsg, exc_info=True)
                    raise
            else:
                rpiLogger.warning("A non-error was raised: %s" % e.errmsg)
                pass

        except RuntimeError as e:
            self._seteventerr('_run()',ERRCRIT)
            rpiLogger.error("RuntimeError: %s\nExiting!" % str(e), exc_info=True)
            raise

        except:
            self._seteventerr('_run()',ERRCRIT)
            rpiLogger.error("Unhandled Exception: %s\nExiting!" % str(sys.exc_info()), exc_info=True)
            raise

        finally:
            self._setstateval()


    def _initclass(self):
        """"
        (re)Initialize the class.
        """

        rpiLogger.info("%s::: Initialize class" % self.name)

        ### Stop and remove the self._run()  and self._proccmd() jobs from the scheduler
        self._remove_run()
        if self._sched is not None:
            with self._sched_lock:
                if self._sched.get_job(self._cmdname) is not None:
                    self._sched.remove_job(self._cmdname)

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

        ### User defined init method
        self.initClass()


        ### Add the self._proccmd() job to the scheduler
        if self._sched is not None:
            with self._sched_lock:
                self._sched.add_job(self._proccmd, trigger='interval', id=self._cmdname , seconds=self._proccmd_interval_sec, misfire_grace_time=5, name=self._cmdname )

        ### Set Init state
        self._init_state()


    def _proccmd(self):
        """
        Set the Stop state if the Job is not scheduled.
        Process and act upon received commands.
        """

        # Set the Stop state if the Job is not scheduled
        if self._sched is not None:
            with self._sched_lock:
                if not self._state['stop'] and self._sched.get_job(self.name) is None:
                    self._stop_state()

        # Process and act upon received commands.
        if self._cmds.empty():
            rpiLogger.debug("%s::: _proccmd: Cmd queue is empty!" % self.name)

        elif (not self.eventDayEnd.is_set()) and (not self.eventEnd.is_set()):

            # Process the command
            (cmdstr, cmdval) = self._cmds.get()

            rpiLogger.debug("%s::: _proccmd: Get cmdstr:%s, cmdval:%d" % (self.name, cmdstr, cmdval))

            if cmdval==CMDRUN and self.setRun():
                self._statusmsg.append(("%s run" % self.name, ERRNONE))

            elif cmdval==CMDSTOP and self.setStop():
                self._statusmsg.append(("%s stop" % self.name, ERRNONE))

            elif cmdval==CMDPAUSE and self.setPause():
                self._statusmsg.append(("%s pause" % self.name, ERRNONE))

            elif cmdval==CMDINIT and self.setInit():
                self._statusmsg.append(("%s init" % self.name, ERRNONE))

            elif cmdval==CMDRESCH and self.setResch():
                self._statusmsg.append(("%s init" % self.name, ERRNONE))

            elif cmdval==CMDEOD and self.setEndDayOAM():
                self._statusmsg.append(("%s eod" % self.name, ERRNONE))

            elif cmdval==CMDEND and self.setEndOAM():
                self._statusmsg.append(("%s end" % self.name, ERRNONE))

            self._cmds.task_done()



    def _setstateval(self):
        """
        Set the combined/encoded state value corresponding to the cmd and err states (4 bits each).
        """
        if self._sched is not None:
            with self._state_lock:
                self._stateVal = self._state['errval'] + 16*self._state['cmdval']


    def _seteventerr(self,str_func,err_val=ERRLEV0):
        """
        Set eventErr, set the error value (ERRLEV0, ERRLEV1, ERRLEV2 or ERRCRIT) and store timestamp.
        """
        if err_val > ERRNONE:
            str = "%s: %s SetError %d" % (self.name, str_func, err_val)
            self._statusmsg.append((str, -1*err_val))
            rpiLogger.debug("%s::: Set eventErr %d in %s at %s!" % (self.name, err_val, str_func, time.ctime(self._eventErrtime)))
            self._eventErr.set()
            self._eventErrtime = time.time()
            self._state['errval'] = err_val
            self._setstateval()

    def _cleareventerr(self,str_func):
        """
        Clear eventErr and reset error value and reset timestamp.
        """
        str = "%s: %s ClrError %d" % (self.name, str_func, self._state['errval'])
        self._statusmsg.append((str, ERRNONE))
        rpiLogger.debug("%s::: Clear eventErr %d in %s!" % (self.name, self._state['errval'], str_func))
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
                    self._sched.add_job(self._run, trigger='interval', id=self.name, seconds=self._interval_sec, start_date=self._dtstart, end_date=self._dtstop, misfire_grace_time=10, name=self.name )
                else:
                    self._reschedule_run(self.name)

        self._run_state()

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

        rpiLogger.debug("%s::: Init state." % self.name)

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

        rpiLogger.debug("%s::: Run state." % self.name)

    def _pause_state(self):

        self._state['run']   = False
        self._state['stop']  = False
        self._state['pause'] = True
        self._state['init']  = False
        self._state['resch'] = False
        self._state['cmdval'] = CMDPAUSE

        self._setstateval()

        rpiLogger.debug("%s::: Pause state." % self.name)

    def _stop_state(self):
        """
        Set Run state for the scheduled self._run() job.
        """
        self._state['run']   = False
        self._state['stop']  = True
        self._state['pause'] = False
        self._state['init']  = False
        self._state['resch'] = False
        self._state['cmdval'] = CMDSTOP

        self._setstateval()

        rpiLogger.debug("%s::: Stop state." % self.name)

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
                    self._sched.reschedule_job(job_id=self.name, trigger='interval', seconds=self._interval_sec, start_date=self._dtstart, end_date=self._dtstop, name=self.name)

        self._state['run']   = False
        self._state['stop']  = False
        self._state['pause'] = False
        self._state['init']  = False
        self._state['resch'] = True
        self._state['cmdval'] = CMDRESCH

        self._setstateval()

        rpiLogger.debug("%s::: Rescheduled state." % self.name)

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

            rpiLogger.info("%s::: endDayOAM(): Maintenance sequence run" % self.name)

            ### Clear the event
            self.eventDayEnd.clear()

        else:
            rpiLogger.debug("%s::: _enddayoam(): eventErr is set" % self.name)


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

            rpiLogger.info("%s::: endOAM(): Maintenance sequence run" % self.name)

            ### Clear the event
            self.eventEnd.clear()

        else:
            rpiLogger.debug("%s::: _endoam(): eventErr is set" % self.name)


    def _create_lock(self):
        """
        Creates a reentrant lock object.
        """
        return RLock()

    def _clean_exit(self):
        """
        An atexit handler for the current job.
        Stop and remove the self._run()  and self._proccmd() jobs from the scheduler.
        """
        rpiLogger.warning("The %s job is exiting!" % self.name)

        self._remove_run()
        
        if self._sched is not None:
            with self._sched_lock:
                if self._sched.get_job(self._cmdname) is not None:
                    self._sched.remove_job(self._cmdname)

        rpiLogger.debug("%s::: Exit!" % self.name)
        self._statusmsg.append(("%s Exit" % self.name, ERRNONE))
