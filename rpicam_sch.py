#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
    Time-lapse with Raspberry Pi controlled camera - Main method
    VER 8 for Python 3.12+
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

TODOs:
1) Enable & debug PIR usage

"""
import os
import sys
import time
import logging
from datetime import datetime, timedelta
from typing import List

#from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_ADDED, EVENT_JOB_REMOVED

### The rpicampy modules
from rpilogger import rpiLogger
from rpiconfig import *
from rpiconfig import journal_send, daemon_notify
import rpievents
from rpibase import ERRCRIT, ERRLEV2, ERRLEV1, ERRLEV0, ERRNONE
import rpimgdir
import rpicam
import rpitimer

if DROPBOXUSE:
    # Dropbox
    from rpimgdb import rpiImageDbxClass
else:
    # Dummy
    from rpibase import rpiBaseClass as rpiImageDbxClass

#if LOCUSBUSE:
#   # USB storage
#   from rpimgusb import rpiImageUSBClass

###
### Local functions
###

def jobListener(event):
    """
    The Job(Execution) Event listener for the APscheduler jobs.
    Process only the main rpi jobs listed in eventsRPi.event_ids.
    :param event: the job event
    """

    #e_exception = getattr(event, 'exception', None)
    e_code = getattr(event, 'code', None)
    e_jobid = getattr(event, 'job_id', None)

    #print("%s, %d, %s" % (e_exception, e_code, e_jobid))
    #print(eventsRPi)


    # Collect and process only the main rpi jobs
    if e_jobid not in eventsRPi.event_ids.values():
        return

    all_sch_jobs = schedRPi.get_jobs()
    sch_jobs=[]
    for jb in all_sch_jobs:
        if jb.id in eventsRPi.event_ids.values():
            sch_jobs.append(jb)

    status_str = None
    if e_code == EVENT_JOB_ERROR:

        # Set job error flag and start counter
        eventsRPi.eventErrList[e_jobid].set()
        eventsRPi.eventErrtimeList[e_jobid]  = time.time()
        eventsRPi.eventErrcountList[e_jobid] += 1
        eventsRPi.eventRuncountList[e_jobid] += 1

        rpiLogger.error("rpicamsch:: jobListener - the job %s crashed %d times (%s)!", e_jobid, eventsRPi.eventErrcountList[e_jobid], time.ctime(eventsRPi.eventErrtimeList[e_jobid]))
        status_str = "%s: Crash %d" % (e_jobid, eventsRPi.eventErrcountList[e_jobid])

    elif e_code == EVENT_JOB_EXECUTED:

        eventsRPi.eventErrcountList[e_jobid]  = 0
        eventsRPi.eventRuncountList[e_jobid] += 1
        eventsRPi.jobRuncount += 1

        if not eventsRPi.eventErrList[e_jobid].is_set():
            status_str = "%s: Run %d" % (e_jobid, eventsRPi.eventRuncountList[e_jobid])

    elif e_code == EVENT_JOB_ADDED:
        if len(sch_jobs):
            for jb in sch_jobs:
                if not (jb.id == e_jobid):
                    if not jb.pending:
                        rpiLogger.debug("rpicamsch:: jobListener - job %s (%s): %s", jb.id, jb.name, jb.next_run_time)
                        status_str = "%s: Add (%d)" % (jb.name, len(sch_jobs))
                    else:
                        rpiLogger.debug("%rpicamsch:: jobListener - job %s (%s): waiting to be added", jb.id, jb.name)
                        status_str = "%s: Pen (%d)" % (jb.name, len(sch_jobs))

    elif e_code == EVENT_JOB_REMOVED:
        if len(sch_jobs) == 1:
            rpiLogger.info("rpicamsch:: jobListener - all %s jobs have been removed!", eventsRPi.event_ids.values())
            eventsRPi.eventAllJobsEnd.set()
            status_str = "NoRPIJobs"

        else:
            status_str = "%s: Rem (%d)" % (e_jobid, len(sch_jobs))

    else:
        rpiLogger.warning("rpicamsch:: jobListener - unhandled event.code = %s", e_code)

    # Update timer status message
    timerConfig['status'] = status_str

def send_log_journal(log_level:str, message: str):
    """
    Send log message to journald and rpiLogger.
    :param log_level: log level string (e.g., 'info', 'debug', 'error', etc.)
    :param message: message string
    """
    journal_send(message)
    eval(f"rpiLogger.{log_level}('rpicamsch:: %s', message)")

### The APScheduler
schedRPi = BackgroundScheduler(alias='BkgScheduler', timezone="Europe/Berlin")

# Add job execution event handler
schedRPi.add_listener(jobListener, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED | EVENT_JOB_ADDED | EVENT_JOB_REMOVED)


### The rpicampy events
eventsRPi = rpievents.rpiEventsClass(RPIJOBNAMES)
rpiLogger.info("rpicamsch:: %s", eventsRPi)

### Instantiate the rpicampy job classes
# Camera
#if camConfig['use_pir'] == 1:
#    # The PIR sensor is used as external trigger for the job
#    imgCam = rpicam.rpiCamClass(RPIJOBNAMES['cam'], None, eventsRPi, camConfig)
#else:

# Camera capture and image buffering
imgCam = rpicam.rpiCamClass(RPIJOBNAMES['cam'], schedRPi, eventsRPi, camConfig)
rpiLogger.info("rpicamsch:: %s", imgCam)

# Remote storage management (Dropbox)
imgDbx = rpiImageDbxClass(RPIJOBNAMES['dbx'], schedRPi, eventsRPi, dbxConfig, imgCam.imageFIFO)
rpiLogger.info("rpicamsch:: %s", imgDbx)

# Local image storage management
imgDir = rpimgdir.rpiImageDirClass(RPIJOBNAMES['dir'], schedRPi, eventsRPi, dirConfig, imgCam.imageFIFO, imgDbx.imageUpldFIFO)
rpiLogger.info("rpicamsch:: %s", imgDir)

# The main timer job (to run continously, regardless of the other jobs)
# This job acts as a collector and dispatcher for status messages from, and the received remote commands to
# all the other jobs above
mainTimer = rpitimer.rpiTimerClass(RPIJOBNAMES['timer'], 
                                   schedRPi, eventsRPi, timerConfig, 
                                   rcConfig,
                                   imgCam, imgDbx, imgDir)
rpiLogger.info("rpicamsch:: %s", mainTimer)

### Main
def main():
    """
    Runs the APScheduler with the image capture jobs scheduled during every specified daily time period.
    """

    # Time period start/stop for image capture and image files management
    tstart_all = datetime(timerConfig['start_year'], timerConfig['start_month'], timerConfig['start_day'], timerConfig['start_hour'][0], timerConfig['start_min'][0], 0, 0)
    tstop_all  = datetime(timerConfig['stop_year'], timerConfig['stop_month'], timerConfig['stop_day'], timerConfig['stop_hour'][-1], timerConfig['stop_min'][-1], 59, 0)

    # Check if the stop time is valid
    tcrt = datetime.now()
    if tcrt >= tstop_all:
        send_log_journal("error", f"Current time {tcrt} is after the end of scheduler activity period {tstop_all}! Image capture scheduler will not be activated! Bye!")
        daemon_notify("STOPPING=1")
        return

    # Start background scheduler
    rpiLogger.debug("rpicamsch:: Image capture scheduler started on: %s", time.ctime(time.time()))
    schedRPi.start()

    # Add the main timer job to run it continously, regardless of the other scheduled jobs.
    mainTimer.setInit()
    mainTimer.errorDelay = 2*timerConfig['interval_sec']
    mainTimer.setRun((None, None, timerConfig['interval_sec']))

    # Enable all other jobs to be scheduled in the main loop
    mainTimer.jobs_enabled = True

    # Notify systemd.daemon and log messsage
    daemon_notify("READY=1")
    send_log_journal("info", f"Image capture scheduler will be active in the period: {tstart_all} - {tstop_all}")

    # Start main loop
    while not rpigexit.kill_now:

        # Wait loop, until the jobs are enabled
        _wait_count = 0
        while not mainTimer.jobs_enabled \
            and not rpigexit.kill_now:
            # Update the systemd watchdog timestamp
            time.sleep(1.0*WATCHDOG_USEC/2000000.0)
            daemon_notify("WATCHDOG=1")

            if _wait_count % 30 == 0:
                send_log_journal("debug", "Image capture scheduler waiting for jobs to be enabled...")
                _wait_count = 0

            _wait_count += 1

        # The daily scheduling loop: every day in the specified time periods
        _wait_count = 0
        tcrt = datetime.now()
        bValidDayPer: List[bool] = [False] * len(timerConfig['start_hour'])
        while tcrt < tstop_all \
            and mainTimer.jobs_enabled \
            and not rpigexit.kill_now:

            # Check the validity of the time periods in the current day
            if tcrt >= tstart_all:
                for tper in range(len(timerConfig['start_hour'])):
                    bValidDayPer[tper] = True
                    if (60*tcrt.hour + tcrt.minute) >= (60*timerConfig['stop_hour'][tper] + timerConfig['stop_min'][tper]):
                        bValidDayPer[tper] = False

            if all(v is False for v in bValidDayPer):
                # Update the systemd watchdog timestamp
                time.sleep(1.0*WATCHDOG_USEC/2000000.0)
                daemon_notify("WATCHDOG=1")

                tcrt = datetime.now()
                if _wait_count % 30 == 0:
                    send_log_journal("debug", f"No valid daily periods for current day {tcrt.date()}. Waiting until next day {tcrt.date() + timedelta(days=1)}...")
                    _wait_count = 0

                _wait_count += 1
                continue # next while tcrt loop

            # Else, run the valid daily periods for the current day
            # Initialize jobs (will run only after EoD, when not initialized already)
            imgCam.setInit()
            imgDir.setInit()
            imgDbx.setInit()
            for tper in range(len(timerConfig['start_hour'])):

                try:

                    # Run only the valid day periods for the current day
                    if not bValidDayPer[tper]:
                        send_log_journal("info", f"The daily period {timerConfig['start_hour'][tper]:02d}:{timerConfig['start_min'][tper]:02d} - {timerConfig['stop_hour'][tper]:02d}:{timerConfig['stop_min'][tper]:02d} was skipped.")
                        continue # next for tper loop

                    # Clear events and set the error delay (grace time) for each job
                    eventsRPi.clearEvents()
                    imgCam.errorDelay = 3*camConfig['interval_sec'][tper]
                    imgDir.errorDelay = 3*dirConfig['interval_sec'][tper]
                    imgDbx.errorDelay = 3*dbxConfig['interval_sec'][tper]

                    # Set the current day period start/stop; the jobs will be run only between tstart_per and tstop_per
                    tstart_per = datetime(tcrt.year, tcrt.month, tcrt.day, timerConfig['start_hour'][tper], timerConfig['start_min'][tper], 0, 0)
                    tstop_per  = datetime(tcrt.year, tcrt.month, tcrt.day, timerConfig['stop_hour'][tper], timerConfig['stop_min'][tper], 59, 0)

                    # Re-initialize start/stop/interval configuration and add the jobs to the scheduler
                    imgCam.setRun((tstart_per, tstop_per, camConfig['interval_sec'][tper]))
                    imgDbx.setRun((tstart_per + timedelta(minutes=1), tstop_per, dbxConfig['interval_sec'][tper]))
                    imgDir.setRun((tstart_per + timedelta(minutes=3), tstop_per, dirConfig['interval_sec'][tper]))

                    send_log_journal("info", f"Running jobs for current day period: {timerConfig['start_hour'][tper]:02d}:{timerConfig['start_min'][tper]:02d} - {timerConfig['stop_hour'][tper]:02d}:{timerConfig['stop_min'][tper]:02d}")

                    # The eventsRPi.eventAllJobsEnd is set when all jobs have been removed/finished
                    while mainTimer.jobs_enabled and \
                        not eventsRPi.eventAllJobsEnd.is_set() and \
                        not rpigexit.kill_now:

                        # Do something else while the jobs are running
                        # ...

                        # Update the systemd watchdog timestamp
                        time.sleep(1.0*WATCHDOG_USEC/2000000.0)
                        daemon_notify("WATCHDOG=1")


                    # Go to next daily period (continue for tper loop) only if jobs are still enabled
                    # and no kill/exit was requested
                    if not mainTimer.jobs_enabled or rpigexit.kill_now:
                        # Stop all the jobs
                        imgCam.setStop()
                        imgDir.setStop()
                        imgDbx.setStop()

                        break # end for tper loop -> next period/day

                    send_log_journal("info", "Current daily period ended.")

                except (KeyboardInterrupt, SystemExit):
                    pass

                except RuntimeError as e:
                    eventsRPi.eventAllJobsEnd.set()
                    mainTimer.jobs_enabled = False
                    rpiLogger.exception("rpicamsch:: RuntimeError: Exiting!\n%s\n", str(e))
                    raise

                except Exception as e:
                    eventsRPi.eventAllJobsEnd.set()
                    mainTimer.jobs_enabled = False
                    rpiLogger.exception("rpicamsch:: Unhandled Exception: Exiting!\n%s\n", str(e))
                    raise

                finally:
                    time.sleep( 10 )


            # Perform the End-of-Day maintenance
            imgCam.setEndDayOAM()
            imgDir.setEndDayOAM()
            imgDbx.setEndDayOAM()

            # Go to next day (continuee while tcrt loop) only if jobs are still enabled
            # and no kill/exit was requested
            if not mainTimer.jobs_enabled or rpigexit.kill_now:
                break # end while tcrt loop -> next day
            
            # Update the current time -> next while tcrt loop
            tcrt = datetime.now()
            send_log_journal("info", "All daily periods ended. Waiting until next day...")

        # Perform the End maintenance
        imgCam.setEndOAM()
        imgDir.setEndOAM()
        imgDbx.setEndOAM()

        # Normal end of the scheduling period or kill/exit was requested
        if not rpigexit.kill_now:
            mainTimer.jobs_enabled = False
            send_log_journal("info", "All image capture job schedules were ended/stopped. Enter waiting loop.")
        else:
            send_log_journal("info", "Exit signal received. All image capture job schedules will be ended/stopped. Bye!")
            break # end/exit program

    # Notify systemd.daemon
    daemon_notify("STOPPING=1")

    # Disable all jobs
    mainTimer.jobs_enabled = False

    # End scheduling
    schedRPi.shutdown(wait=True)
    rpiLogger.debug("rpicamsch:: Image capture scheduler stopped on: %s", time.ctime(time.time()))

    # Shutdown logging
    rpiLogger.handlers.clear()
    logging.shutdown()
    time.sleep( 10 )

if __name__ == "__main__":
    main()
