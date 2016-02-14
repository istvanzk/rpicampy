#!/usr/local/bin/python3.4
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
rpicam_sch:	The main method. Uses APScheduler (Advanced Python Scheduler: http://apscheduler.readthedocs.org/en/latest/) 
			to background schedule three interval jobs implemented in: rpicam, rpimgdir and rpimgdb. 
			An additional ThingSpeak TalkBack job is also scheduled.
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
from collections import deque
import yaml
import subprocess

# APScheduler
#from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_ADDED, EVENT_JOB_REMOVED

import rpimgdir
import rpicam
import rpimgdb
import rpievents
import thingspk

### DB API keys
DBTOKEN_FILE = 'token_key.txt'

### ThingSpeak API feed and TalkBack app
TSPK_FILE   = 'tspk_keys.txt'
TSPKFEEDUSE = True
TSPKTBUSE   = True


### Set up the logging
logging.basicConfig(filename='rpicam.log', filemode='w',
					level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] (%(threadName)-10s) %(message)s',
                    )

### Python version
PY34 = (sys.version_info[0] == 3) and (sys.version_info[1] == 4)

### Host/cam ID
CAMID = 'CAM1'
if subprocess.check_output(["hostname", ""], shell=True).strip().decode('utf-8').find('pi2') > 0:
	CAMID = 'CAM2'

### Read the parameters
try:
	with open('rpiconfig.yaml', 'r') as stream:
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

	logging.info("Configuration file read.")
				
except yaml.YAMLError as e:
	logging.error("Error in configuration file:" % e)
	os._exit()
	
finally:			
	logging.debug("timerConfig: %s" % timerConfig)
	logging.debug("camConfig: %s" % camConfig)
	logging.debug("dirConfig: %s" % dirConfig)
	logging.debug("dbxConfig: %s" % dbxConfig)

### ThingSpeak feed
if TSPKFEEDUSE:
	RESTfeed = thingspk.ThingSpeakAPIClient(TSPK_FILE)
	logging.info("ThingSpeak Channel ID %d initialized" % RESTfeed.channel_id)
else:
	RESTfeed = None

### Init the ThingSpeak REST feed data
if TSPKFEEDUSE and (RESTfeed is not None):
	RESTfeed.setfield('field1', 0) 
	RESTfeed.setfield('field2', 0) 
	RESTfeed.setfield('field3', 0)
	RESTfeed.setfield('field4', 0)		
						
### ThingSpeak TalkBack 
if TSPKTBUSE:
	RESTTalkB = thingspk.ThingSpeakTBClient(TSPK_FILE)
	logging.info("ThingSpeak TalkBack ID %d initialized" % RESTTalkB.talkback_id)
else:
	RESTTalkB = None
	


	
###	
### Methods
###
def restUpdate(status_str=None, stream_value=None):
	"""
	REST API wrapper method to update feed/status value.
	The actual REST call is performed in restPost()! 			
	"""
	if RESTfeed is not None:
		RESTfeed.setfield('status','')	
		if status_str is not None: 
			RESTfeed.setfield('status',status_str)
		if stream_value is not None:
			RESTfeed.setfield('field1', stream_value)	
								
def jobListener(event):
	"""
	The Job(Execution) Event listener for the APscheduler jobs.
	"""
	
	#e_exception = getattr(event, 'exception', None)
	e_code = getattr(event, 'code', None)	
	e_jobid = getattr(event, 'job_id', None)
	
	#job = None
	#if e_jobid is not None:
	
	#print("%s, %d, %s" % (e_exception, e_code, e_jobid))
	#print(eventsRPi)
		
	status_str = None	
	if e_code == EVENT_JOB_ERROR:
	
		# Clear error flag to allow the other jobs to run normally
		eventsRPi.eventErrList[e_jobid].clear()
		eventsRPi.eventErrtimeList[e_jobid]  = 0 
		eventsRPi.eventErrdelayList[e_jobid] = 0 
		
		logging.error("%s: The job crashed!" % e_jobid)
		restUpdate("%s: Crash" % e_jobid)
	
	elif e_code == EVENT_JOB_EXECUTED:

		eventsRPi.eventRuncountList[e_jobid] += 1
		eventsRPi.jobRuncount += 1
		
		if not eventsRPi.eventErrList[e_jobid].is_set():
			status_str = "%s: Run %d" % (e_jobid, eventsRPi.eventRuncountList[e_jobid])
		
	elif e_code == EVENT_JOB_ADDED: 
		sch_jobs = sched.get_jobs()
		if len(sch_jobs):
			for jb in sch_jobs:
				if not (jb.id == e_jobid):
					if not jb.pending:
						logging.debug("%s (%s): %s" % (jb.id, jb.name, jb.next_run_time))
						status_str = "%s: Add (%d)" % (jb.name, len(sch_jobs))
					else:
						logging.debug("%s (%s): waiting to be added" % (jb.id, jb.name))
						status_str = "%s: Pen (%d)" % (jb.name, len(sch_jobs))
						
	elif e_code == EVENT_JOB_REMOVED:	
		sch_jobs = sched.get_jobs()		
		if ((RESTTalkB is not None) and (len(sch_jobs) == 1)) or \
			((RESTTalkB is None) and (len(sch_jobs) == 0)):
			logging.info("All rpi jobs have been removed!")
			eventsRPi.eventAllJobsEnd.set()
			status_str = "NoRPIJobs"
			
		else:
			status_str = "%s: Rem (%d)" % (e_jobid, len(sch_jobs))
			
	else:
		logging.warning("Unhandled event.code = %s" % e_code)
	 
	# Update REST status feed 	
	restUpdate(status_str)


def procCmdRx(cmdval, imgClass):
	"""
	Process a TalkBack command value.
	Set the numerical value for the current state.
	"""

	# Process the command
	if cmdval==3 and imgClass.setRun():
		sched.resume_job(dictConfig['jobid'])
		restUpdate("%s run" % imgClass.name)

	elif cmdval==0 and imgClass.setStop():
		sched.remove_job(dictConfig['jobid'])
		restUpdate("%s stop" % imgClass.name)

	elif cmdval==1 and imgClass.setPause():
		sched.pause_job(dictConfig['jobid'])
		restUpdate("%s pause" % imgClass.name)

	elif cmdval==2 and imgClass.setInit():
		restUpdate("%s init" % imgClass.name)

	
def procStateVal():
	"""
	Post the combined state (cmd and err) values for all jobs
	"""
	
	# The combined state (cmd and err) values for all jobs
	state_val = eventsRPi.stateValList[imgCam.name] + 16*eventsRPi.stateValList[imgDir.name] + 16*16*eventsRPi.stateValList[imgdbx.name]

	# Update REST feed with a new state value only
	if timerConfig['stateval'] != state_val:
		timerConfig['stateval'] = state_val
		restUpdate(stream_value=state_val)			

		
def restJob():
	"""
	ThingSpeak TalkBack APP command handler (scheduled Job).
	ThingSpeak REST API post data for all feeds and status. 
	"""

	if RESTTalkB is not None:

		RESTTalkB.talkback.execcmd()
		res = RESTTalkB.talkback.response
		if res:
			logging.debug("TB response: %s" % RESTTalkB.talkback.response)
			cmdrx = res.get('command_string')

			# Get cmd string and value
			cmdstr = cmdrx.split('/',1)[0]
			cmdval = int(cmdrx.split('/',1)[1])

			# Cmd mode
			if cmdrx==u'cmd/01' and not timerConfig['cmd_run']:
				timerConfig['cmd_run'] = True
				sched.reschedule_job(job_id="TBJob", trigger='interval', seconds=timerConfig['interval_sec'][1])
				logging.debug("TBCmd fast mode enabled.")
				restUpdate("TBCmd activated")

			elif cmdrx==u'cmd/00' and timerConfig['cmd_run']:
				timerConfig['cmd_run'] = False
				sched.reschedule_job(job_id="TBJob", trigger='interval', seconds=timerConfig['interval_sec'][0])
				logging.debug("TBCmd fast mode disabled.")
				restUpdate("TBCmd standby")

			# Timer
			elif cmdrx==u'sch/01' and not timerConfig['enabled']:
				timerConfig['enabled'] = True
				logging.debug("JobSch enabled.")
				restUpdate("JobSch enabled")

			elif cmdrx==u'sch/00' and timerConfig['enabled']:
				timerConfig['enabled'] = False
				logging.debug("JobSch disabled.")
				restUpdate("JobSch disabled")

			
			# These commands are active only in cmd mode
			if timerConfig['cmd_run']:
				
				# Cam
				if cmdstr == u'cam':
					procCmdRx(cmdval, imgCam)

				# Dir
				elif cmdstr == u'dir':
					procCmdRx(cmdval, imgDir)

				# Dbx
				elif cmdstr == u'dbx':
					procCmdRx(cmdval, imgDbx)

	# Update state value
	procStateVal()

	# Update REST feed
	if RESTfeed is not None:					
		RESTfeed.update()
		
		
### The events
eventsRPi = rpievents.rpiEventsClass(['CAMJob', 'DIRJob', 'DBXJob', 'TBJob'])
logging.debug(eventsRPi)

### Instantiate the job classes	
imgCam = rpicam.rpiCamClass("CAMJob", camConfig, eventsRPi, RESTfeed, 'field2') 
logging.info(imgCam)

imgDir = rpimgdir.rpiImageDirClass(imgCam.imageFIFO, "DIRJob", dirConfig, eventsRPi, RESTfeed, 'field3')
logging.info(imgDir)

imgDbx = rpimgdb.rpiImageDbClass(imgCam.imageFIFO, "DBXJob", dbxConfig, eventsRPi, RESTfeed, 'field4')
logging.info(imgDbx)


### The APScheduler
sched = BackgroundScheduler(alias='BkgScheduler')
#sched = BlockingScheduler(alias='BlkScheduler')

# Add job execution event handler
sched.add_listener(jobListener, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED | EVENT_JOB_ADDED | EVENT_JOB_REMOVED) 


### Main 		
def main():
	"""
	Runs the Scheduler with the Jobs on every day in the set time periods.
	"""
	
	### Time period start/stop
	tstart_all = datetime(timerConfig['start_year'], timerConfig['start_month'], timerConfig['start_day'], timerConfig['start_hour'][0], timerConfig['start_min'][0], 0, 0)
	tstop_all  = datetime(timerConfig['stop_year'], timerConfig['stop_month'], timerConfig['stop_day'], timerConfig['stop_hour'][-1], timerConfig['stop_min'][-1], 59, 0)
		
				
	### Check if the time period is valid
	tnow = datetime.now()
	if tnow >= tstop_all:
		logging.warning("Current time (%s) is after the end of scheduler activity period (%s)!" % (tnow, tstop_all))
		logging.info("Scheduler was not started! Bye!")
		print("Scheduler was not started! Bye!")
		
		# Update REST feed (now) 
		restUpdate('NoStart')
		restJob()
		time.sleep( 60 )
		
		return
	
			
	### Start background scheduler
	logging.debug("Scheduler started on: %s" % (time.ctime(time.time())))
	sched.start()

	logging.info("Scheduler will be active in the period: %s - %s" % (tstart_all, tstop_all))
	print("Scheduler will be active in the period: %s - %s" % (tstart_all, tstop_all))

	# Update REST feed (now) 
	restUpdate('Start')
	restJob()

	# Add REST client job; run every preset (long) interval
	if RESTTalkB is not None:
		sched.add_job(restJob, 'interval', id="RESTJob", seconds=timerConfig['interval_sec'][0], misfire_grace_time=10, name='REST' )

	# Main loop
	MainRun = True
	while MainRun:

		while not timerConfig['enabled']: 
			# Wait until timer is enabled		
			time.sleep( timerConfig['interval_sec'][1] )
			restUpdate('Waiting')			
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
					logging.info("The daily period %02d:%02d - %02d:%02d was skipped." % (timerConfig['start_hour'][tper], timerConfig['start_min'][tper], timerConfig['stop_hour'][tper], timerConfig['stop_min'][tper]))
			
		# The scheduling period: every day in the given time periods
		while tcrt < tstop_all:

			# Loop over the defined day periods	
			for tper in range(len(timerConfig['start_hour'])):

				# Run only the valid day periods
				if not bValidDayPer[tper]:
					continue # next period/day

				# The current day period start/stop; the jobs will be run only between tstart_per and tstop_per 
				tstart_per = datetime(tcrt.year, tcrt.month, tcrt.day, timerConfig['start_hour'][tper], timerConfig['start_min'][tper], 0, 0)
				tstop_per  = datetime(tcrt.year, tcrt.month, tcrt.day, timerConfig['stop_hour'][tper], timerConfig['stop_min'][tper], 59, 0)

				# Schedule the jobs to be run in the configured time period. All are paused until the scheduler is started			
				eventsRPi.clearEvents()
				try:
					# Re-init the jobs when they run the first time
					if not MainRun:
						imgCam.setInit()
						imgDir.setInit()
						imgDbx.setInit()
					
					# The jobs will be run only between tstart_per and tstop_per 
					sched.add_job(imgCam.run, 'interval', id=imgCam.name, seconds=camConfig['interval_sec'][tper], start_date=tstart_per, end_date=tstop_per, misfire_grace_time=10, name='CAM' )
					sched.add_job(imgDir.run, 'interval', id=imgDir.name, seconds=dirConfig['dircheck_sec'][tper], start_date=tstart_per+timedelta(minutes=+1), end_date=tstop_per, misfire_grace_time=10, name='DIR' )
					sched.add_job(imgDbx.run, 'interval', id=imgDbx.name, seconds=dbxConfig['dbcheck_sec'][tper], start_date=tstart_per+timedelta(minutes=+2), end_date=tstop_per, misfire_grace_time=10, name='DBX' )

					# The eventsRPi.eventAllJobsEnd is set when all jobs have been removed/finished
					while timerConfig['enabled'] and not eventsRPi.eventAllJobsEnd.is_set():		 	

						# Do something else while the scheduler is running
						time.sleep(10)



					# Go to next daily period only if timer is still enabled
					if not timerConfig['enabled']:		
					
						# Remove the jobs
						sched.remove_job("CAMJob")
						sched.remove_job("DIRJob")
						sched.remove_job("DBXJob")		
							
						# Mark with Stop all the jobs
						imgCam.setStop()
						imgDir.setStop()
						imgDbx.setStop()
											
						break # end the for tper loop


				except (KeyboardInterrupt, SystemExit):
					pass

				except RuntimeError as e:
					self.eventEnd.set()
					logging.error("RuntimeError: %s! Exiting!" % str(e), exc_info=True)
					raise

				except:
					self.eventEnd.set()
					logging.error("Exception: %s! Exiting!" %  str(sys.exc_info()), exc_info=True)
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
			eventsRPi.eventDayEnd.set()
			imgCam.run()
			imgDir.run()
			imgDbx.run()
			restUpdate('EoD-OAM')
		
			# Go to next day only if timer is still enabled
			if not timerConfig['enabled']:		
				break # end the while tcrt loop
			
			
		# Perform the End maintenance
		eventsRPi.eventEnd.set()
		imgCam.run()
		imgDir.run()
		imgDbx.run()
		restUpdate('End-OAM')

		# Normal end of the scheduling period (exit) or enter wait loop
		if timerConfig['enabled']:
			MainRun = False
			
		else:
			logging.info("Job schedules were ended. Enter waiting loop.")

	# End scheduler	
	timerConfig['enabled'] = False	
	sched.shutdown(wait=True)
	logging.debug("Scheduler stop on: %s" % time.ctime(time.time()))

	# Update REST feed (now) 
	restUpdate('Stop')
	restJob()
	time.sleep( 60 )

if __name__ == "__main__":
	main() 
