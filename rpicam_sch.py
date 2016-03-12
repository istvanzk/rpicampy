#!/usr/local/bin/python3.4
# -*- coding: utf-8 -*-

"""
Time-lapse with Rasberry Pi controlled camera - VER 4.5 for Python 3.4+
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

Modules:

rpibase:	Base class for rpicam, rpimgdir and rpimgdb
rpicam:		Run and control a:
			- Raspberry PI camera using using the picamera module, or
			- Raspberry PI camera using the raspistill utility, or
			- USB web camera using fswebcam utility
rpimgdir:	Manage the set of saved images by rpiCam.
rpimgdb:	Manage images in a remote directory (Dropbox SDK, API V2, Python 3.4).
rpievents:	Implements the the set of events and counters to be used in the rpi job.
rpififo:	Implements the a FIFO buffer for the image file names (full path) generated in the rpicam job.
thingspk:	A simple REST request abstraction layer and a light ThingSpeak API and TalkBack App SDK.
rpicam_sch:	The main method. Uses APScheduler (Advanced Python Scheduler: http://apschedRPiuler.readthedocs.org/en/latest/)
			to background schedRPiule three interval jobs implemented in: rpicam, rpimgdir and rpimgdb.
			An additional ThingSpeak TalkBack job is also schedRPiuled.
rpiconfig.yaml:	The configuration parameters.

The image file names are:  '%d%m%y-%H%M%S-CAMX.jpg', where CAMX is the camera identification (ID string).
The images are saved locally and remotely in a sub-folder. The sub-folder name is the current date '%d%m%y'.

The implementation of the thingspk module follows the ThingSpeak API documentation at https://www.mathworks.com/help/thingspeak/
and the TalkBack API documentation at https://www.mathworks.com/help/thingspeak/talkback-app.html
The REST client implementation follows the model of the official python Xively API client (SDK).

The tool can be launched as an init.d Linux service with the rpicamtest.sh

TODOs:
1) Implement Job crash recovery mechanism.
2) Use "Automatically reload python module / package on file change" from https://gist.github.com/eberle1080/1013122
and pyinotify module, http://www.saltycrane.com/blog/2010/04/monitoring-filesystem-python-and-pyinotify/
3) Integrate with RasPiConnectServer
4) Use configurable logging (http://victorlin.me/posts/2012/08/26/good-logging-practice-in-python)

"""

import os
import sys
import time
from datetime import datetime, timedelta
import logging
import logging.handlers
from collections import deque
import yaml
import subprocess

# APScheduler
#from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_ADDED, EVENT_JOB_REMOVED

from rpibase import ERRCRIT, ERRLEV2, ERRLEV1, ERRLEV0, ERRNONE
import rpimgdir
import rpicam
import rpimgdb
import rpievents
import thingspk

### Configuration

# Configuration file
YAMLCFG_FILE = 'rpiconfig.yaml'

# DB API token file
DBTOKEN_FILE = 'token_key.txt'

# ThingSpeak API feed and TalkBack app
TSPK_FILE   = 'tspk_keys.txt'
TSPKFEEDUSE = True
TSPKTBUSE   = True

# Logging parameters
LOGLEVEL = logging.INFO
LOGFILEBYTES = 3*102400

# RPi Job names
RPIJOBNAMES = {'timer':'TIMERJob', 'cam':'CAMJob', 'dir':'DIRJob', 'dbx':'DBXJob'}

# ThingSpeak feed field names mapping
TSPKFIELDNAMES = {'timer':'field1', 'cam':'field2', 'dir':'field3', 'dbx':'field4'}


### End of Configuration


### Python version
PY34 = (sys.version_info[0] == 3) and (sys.version_info[1] == 4)

### Host/cam ID
CAMID = 'CAM1'
if subprocess.check_output(["hostname", ""], shell=True).strip().decode('utf-8').find('pi2') > 0:
	CAMID = 'CAM2'

### Set up the logging and a filter
class NoRunningFilter(logging.Filter):

    def __init__(self, filter_str=""):
    	logging.Filter.__init__(self, filter_str)
    	self.filterstr = filter_str

    def filter(self, rec):
    	if self.filterstr in rec.getMessage():
    		return False
    	else:
    		return True

### Does not work with logger/handler filter!
# logging.basicConfig(filename='rpicam.log', filemode='w',
# 					level=logging.INFO,
#                     format='%(asctime)s [%(levelname)s] (%(threadName)-10s) %(message)s',
#                     )

rpiLogger = logging.getLogger()
rpiLogger.setLevel(logging.DEBUG)

#hndl = logging.FileHandler(filename='rpicam.log', mode='w')
hndl = logging.handlers.RotatingFileHandler(filename='rpicam.log', mode='w', maxBytes=LOGFILEBYTES, backupCount=5)
formatter = logging.Formatter('%(asctime)s [%(levelname)s] (%(threadName)-10s) %(message)s')
hndl.setLevel(LOGLEVEL)
hndl.setFormatter(formatter)

# Filter out all messages which are not from the main Jobs
filter = NoRunningFilter('Job_Cmd')
hndl.addFilter(filter)

#rpiLogger.addFilter(filter)
rpiLogger.addHandler(hndl)

rpiLogger.info("\n\n======== Start %s (loglevel:%d) ========\n" % (CAMID, LOGLEVEL))

### Read the parameters
try:
	with open(YAMLCFG_FILE, 'r') as stream:
		timerConfig, camConfig, dirConfig, dbxConfig = yaml.load_all(stream)

	# Add config keys
	dbxConfig['token_file'] = DBTOKEN_FILE
	dbxConfig['image_dir']  = camConfig['image_dir']
	dirConfig['image_dir']  = camConfig['image_dir']
	camConfig['list_size']  = dirConfig['list_size']

	# Operation control flags
	timerConfig['enabled'] = True
	timerConfig['cmd_run'] = False
	timerConfig['stateval']= 0
	timerConfig['status']  = ''

	rpiLogger.info("Configuration file read")

except yaml.YAMLError as e:
	rpiLogger.error("Error in configuration file:" % e)
	os._exit()

rpiLogger.debug("timerConfig: %s" % timerConfig)
rpiLogger.debug("camConfig: %s" % camConfig)
rpiLogger.debug("dirConfig: %s" % dirConfig)
rpiLogger.debug("dbxConfig: %s" % dbxConfig)

### ThingSpeak feed
if TSPKFEEDUSE:
	RESTfeed = thingspk.ThingSpeakAPIClient(TSPK_FILE)
	if RESTfeed is not None:
		rpiLogger.info("ThingSpeak Channel ID %d initialized" % RESTfeed.channel_id)
		for tsf in TSPKFIELDNAMES.values():
			RESTfeed.setfield(tsf, 0)
		RESTfeed.setfield('status', '---')
else:
	RESTfeed = None


### ThingSpeak TalkBack
if TSPKTBUSE:
	RESTTalkB = thingspk.ThingSpeakTBClient(TSPK_FILE)
	rpiLogger.info("ThingSpeak TalkBack ID %d initialized" % RESTTalkB.talkback_id)
else:
	RESTTalkB = None




###
### Methods
###

def jobListener(event):
	"""
	The Job(Execution) Event listener for the APscheduler jobs.
	Process only the main rpi jobs listed in eventsRPi.event_ids.
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

		rpiLogger.error("%s: The job crashed %d times (%s)!" % (e_jobid, eventsRPi.eventErrcountList[e_jobid], time.ctime(eventsRPi.eventErrtimeList[e_jobid])))
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
						rpiLogger.debug("%s (%s): %s" % (jb.id, jb.name, jb.next_run_time))
						status_str = "%s: Add (%d)" % (jb.name, len(sch_jobs))
					else:
						rpiLogger.debug("%s (%s): waiting to be added" % (jb.id, jb.name))
						status_str = "%s: Pen (%d)" % (jb.name, len(sch_jobs))

	elif e_code == EVENT_JOB_REMOVED:
		if len(sch_jobs) == 1:
			rpiLogger.info("All %s jobs have been removed!" % eventsRPi.event_ids.values())
			eventsRPi.eventAllJobsEnd.set()
			status_str = "NoRPIJobs"

		else:
			status_str = "%s: Rem (%d)" % (e_jobid, len(sch_jobs))

	else:
		logging.warning("Unhandled event.code = %s" % e_code)

	# Update timer status message
	timerConfig['status'] = status_str



def procStateVal():
	"""
	Calculate the combined state (cmd and err) values for all rpi jobs.
	"""
	timer_stateval = 0
	# Add the timer job error state (lower 4 bits)

	# Add the timer job cmd state (upper 4 bits)
	if timerConfig['enabled']:
		timer_stateval += 16*1
	if timerConfig['cmd_run']:
		timer_stateval += 16*2

	# Store state values
	eventsRPi.stateValList[imgCam.name] = imgCam.stateValue
	eventsRPi.stateValList[imgDir.name] = imgDir.stateValue
	eventsRPi.stateValList[imgDbx.name] = imgDbx.stateValue
	eventsRPi.stateValList['TIMERJob'] = timer_stateval

	# The combined state (cmd 4bits + err 4bits) values for all jobs
	timerConfig['stateval'] = 256*256*256*eventsRPi.stateValList['TIMERJob']
	timerConfig['stateval'] += eventsRPi.stateValList[imgCam.name] + 256*eventsRPi.stateValList[imgDir.name] + 256*256*eventsRPi.stateValList[imgDbx.name]


def getMessageVal():
	"""
	Retrieve the latest messages and message values from all rpi jobs.
	"""
	st_all = {}
	st_all['timer'] = (timerConfig['status'], timerConfig['stateval']) #has to be changed to use a deque?
	st_all[[k for k,v in RPIJOBNAMES.items() if v == imgCam.name][0]] = imgCam.statusUpdate
	st_all[[k for k,v in RPIJOBNAMES.items() if v == imgDir.name][0]] = imgDir.statusUpdate
	st_all[[k for k,v in RPIJOBNAMES.items() if v == imgDbx.name][0]] = imgDbx.statusUpdate

	status_message = None
	messages = []
	message_values = {}
	for k, (msg, val) in st_all.items():
		if msg is not None:
			messages.append(msg)

		if val > ERRNONE or \
			( val == ERRNONE and msg is not None) :
			message_values[TSPKFIELDNAMES[k]] = val

	if not messages==[]:
		status_message = ' || '.join(messages)

	return status_message, message_values

def timerJob():
	"""
	ThingSpeak TalkBack APP command handler and dispatcher for the rpi scheduled jobs.
	Collect and combine the status messages from the rpi scheduled jobs.
	ThingSpeak REST API post data for all feeds and status.
	"""

	### Default
	cmdstr = u'none'
	cmdval = -1

	### Get command from ThingSpeak Talk Back APP
	if RESTTalkB is not None:
		RESTTalkB.talkback.execcmd()
		res = RESTTalkB.talkback.response
		if res:
			rpiLogger.debug("TB response: %s" % RESTTalkB.talkback.response)
			cmdrx = res.get('command_string')

			# Get cmd string and value
			cmdstr = cmdrx.split('/',1)[0]
			cmdval = int(cmdrx.split('/',1)[1])


	### Handle and dispatch the received commands

	# Timer
	if cmdstr==u'sch':
		if cmdval==1 and not timerConfig['enabled']:
			timerConfig['enabled'] = True
			rpiLogger.debug("JobSch enabled.")
			timerConfig['status'] = "JobSch enabled"

		elif cmdval==0 and timerConfig['enabled']:
			timerConfig['enabled'] = False
			rpiLogger.debug("JobSch disabled.")
			timerConfig['status'] = "JobSch disabled"

	# Cmd mode
	elif cmdstr==u'cmd':
		if cmdval==1 and not timerConfig['cmd_run']:
			timerConfig['cmd_run'] = True
			schedRPi.reschedule_job(job_id="TIMERJob", trigger='interval', seconds=timerConfig['interval_sec'][1])
			rpiLogger.debug("TBCmd fast mode enabled.")
			timerConfig['status'] = "TBCmd activated"

		elif cmdval==0 and timerConfig['cmd_run']:
			timerConfig['cmd_run'] = False
			schedRPi.reschedule_job(job_id="TIMERJob", trigger='interval', seconds=timerConfig['interval_sec'][0])
			rpiLogger.debug("TBCmd fast mode disabled.")
			timerConfig['status'] = "TBCmd standby"


	# These commands are active only in cmd mode
	if timerConfig['cmd_run']:

		# Cam control
		if cmdstr == u'cam':
			imgCam.queueCmd((cmdstr,cmdval))

		# Dir control
		elif cmdstr == u'dir':
			imgDir.queueCmd((cmdstr,cmdval))

		# Dbx control
		elif cmdstr == u'dbx':
			imgDbx.queueCmd((cmdstr,cmdval))


	### Get the combined state value (all rpi jobs)
	procStateVal()

	### Get status messages and message values (all rpi jobs)
	status_message, message_values = getMessageVal()


	### Update ThingSpeak feed
	if RESTfeed is not None:
		for k in message_values:
			RESTfeed.setfield(k, message_values[k])

		if status_message is not None:
			RESTfeed.setfield('status', status_message)

		RESTfeed.update()



### The APScheduler
schedRPi = BackgroundScheduler(alias='BkgScheduler')
#schedRPi = BlockingScheduler(alias='BlkScheduler')

# Add job execution event handler
schedRPi.add_listener(jobListener, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED | EVENT_JOB_ADDED | EVENT_JOB_REMOVED)


### The events
eventsRPi = rpievents.rpiEventsClass(RPIJOBNAMES)
rpiLogger.info(eventsRPi)

### Instantiate the job classes
imgCam = rpicam.rpiCamClass(RPIJOBNAMES['cam'], schedRPi, eventsRPi, camConfig)
rpiLogger.info(imgCam)

imgDbx = rpimgdb.rpiImageDbxClass(RPIJOBNAMES['dbx'], schedRPi, eventsRPi, dbxConfig, imgCam.imageFIFO)
rpiLogger.info(imgDbx)

imgDir = rpimgdir.rpiImageDirClass(RPIJOBNAMES['dir'], schedRPi, eventsRPi, dirConfig, imgCam.imageFIFO, imgDbx.imageUpldFIFO)
rpiLogger.info(imgDir)


### Main
def main():
	"""
	Runs the APScheduler with the Jobs on every day in the set time periods.
	"""

	### Time period start/stop
	tstart_all = datetime(timerConfig['start_year'], timerConfig['start_month'], timerConfig['start_day'], timerConfig['start_hour'][0], timerConfig['start_min'][0], 0, 0)
	tstop_all  = datetime(timerConfig['stop_year'], timerConfig['stop_month'], timerConfig['stop_day'], timerConfig['stop_hour'][-1], timerConfig['stop_min'][-1], 59, 0)


	### Check if the time period is valid
	tnow = datetime.now()
	if tnow >= tstop_all:
		logging.warning("Current time (%s) is after the end of schedRPiuler activity period (%s)!" % (tnow, tstop_all))
		rpiLogger.info("Scheduler was not started! Bye!")
		print("Scheduler was not started! Bye!")

		# Update status
		timerConfig['status'] = 'NoStart'
		timerJob()
		time.sleep( 60 )

		return

	### Add the main timer client job; run every preset (long) interval
	schedRPi.add_job(timerJob, 'interval', id=RPIJOBNAMES['timer'], seconds=timerConfig['interval_sec'][0], misfire_grace_time=10, name='TIMER' )

	### Start background scheduler
	rpiLogger.debug("Scheduler started on: %s" % (time.ctime(time.time())))
	schedRPi.start()

	rpiLogger.info("Scheduler will be active in the period: %s - %s" % (tstart_all, tstop_all))
	print("Scheduler will be active in the period: %s - %s" % (tstart_all, tstop_all))

	# Update status
	timerConfig['status'] = 'SchStart'
	timerJob()

	# Main loop
	MainRun = True
	while MainRun:

		while not timerConfig['enabled']:
			# Wait until timer is enabled
			time.sleep( timerConfig['interval_sec'][1] )
			timerConfig['status'] ='Waiting'
			MainRun = False
			continue

		# Enable all day periods
		bValidDayPer = []
		for tper in range(len(timerConfig['start_hour'])):
			bValidDayPer.append(True)

		# Check the validity of the periods on the first day (tnow)
		tcrt = datetime.now()
		if tcrt >= tstart_all:
			for tper in range(len(timerConfig['start_hour'])):
				if (60*tcrt.hour + tcrt.minute) >= (60*timerConfig['stop_hour'][tper] + timerConfig['stop_min'][tper]):
					bValidDayPer[tper] = False
					rpiLogger.info("The daily period %02d:%02d - %02d:%02d was skipped." % (timerConfig['start_hour'][tper], timerConfig['start_min'][tper], timerConfig['stop_hour'][tper], timerConfig['stop_min'][tper]))

		# The schedRPiuling period: every day in the given time periods
		while tcrt < tstop_all:

			# Initialize jobs (will run only after EoD, when not initialized already)
			imgCam.setInit()
			imgDir.setInit()
			imgDbx.setInit()

			# Loop over the defined day periods
			for tper in range(len(timerConfig['start_hour'])):

				try:

					# Run only the valid day periods
					if not bValidDayPer[tper]:
						continue # next period/day

					# Clear events and set the error delay (grace period) for each job
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


					# The eventsRPi.eventAllJobsEnd is set when all jobs have been removed/finished
					while timerConfig['enabled'] and not eventsRPi.eventAllJobsEnd.is_set():

						# Do something else while the schedRPiuler is running
						time.sleep(10)


					# Go to next daily period only if timer is still enabled
					if not timerConfig['enabled']:

						# Stop all the jobs
						imgCam.setStop()
						imgDir.setStop()
						imgDbx.setStop()

						break # end the for tper loop


				except (KeyboardInterrupt, SystemExit):
					pass

				except RuntimeError as e:
					eventsRPi.eventEnd.set()
					rpiLogger.error("RuntimeError: %s! Exiting!" % str(e), exc_info=True)
					raise

				except:
					eventsRPi.eventEnd.set()
					rpiLogger.error("Exception: %s! Exiting!" %  str(sys.exc_info()), exc_info=True)
					raise

				finally:
					time.sleep( 60 )


			# Next day 00:00 time
			tnow = datetime.now()
			tcrt = datetime(tnow.year, tnow.month, tnow.day, 0, 0, 0, 0) + timedelta(days=1)

			# Enable all day periods
			for tper in range(len(timerConfig['start_hour'])):
				bValidDayPer[tper] = True

			# Perform the End-of-Day maintenance
			imgCam.setEndDayOAM()
			imgDir.setEndDayOAM()
			imgDbx.setEndDayOAM()

			# Go to next day only if timer is still enabled
			if not timerConfig['enabled']:
				break # end the while tcrt loop


		# Perform the End maintenance
		imgCam.setEndOAM()
		imgDir.setEndOAM()
		imgDbx.setEndOAM()

		# Normal end of the schedRPiuling period (exit) or enter wait loop
		if timerConfig['enabled']:
			MainRun = False

		else:
			rpiLogger.info("All job schedules were ended. Enter waiting loop.")

	# End schedRPiuler
	timerConfig['enabled'] = False
	schedRPi.shutdown(wait=True)
	rpiLogger.debug("Scheduler stop on: %s" % time.ctime(time.time()))

	# Update REST feed (now)
	timerConfig['status'] = 'SchStop'
	timerJob()
	logging.shutdown()
	time.sleep( 60 )

if __name__ == "__main__":
	main()
