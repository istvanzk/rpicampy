#!/usr/local/bin/python3.4
# -*- coding: utf-8 -*-

"""
Time-lapse with Rasberry Pi controlled camera - VER 3.0 for Python 3.4+
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

Uses APScheduler (Advanced Python Scheduler: http://pythonhosted.org/APScheduler/) 
to background schedule three interval jobs: 
	1. rpicam:		Run and control a:
					- Raspberry PI camera using using the picamera module, or
					- Raspberry PI camera using the raspistill utility, or 
					- USB web camera using fswebcam utility 
	2. rpimgdir:	Manage the set of saved images by rpiCam.  
	3. rpimgdb:		Manage images in a remote directory (Dropbox SDK, API V2, Python 3.4).

The configuration parameters are read from the rpiconfig.yaml

The image file names are: '%d%m%y-%H%M%S-CAM.jpg', where X is the camera number (ID string). 
The images are saved locally and remotely in a sub-folder. The sub-folder name is the current date '%d%m%y'

A simple REST request abstraction layer and a light ThingSpeak API SDK is provided in the thingspeak module. 
The implementation follows to the API documentation at http://community.thingspeak.com/documentation/api/ and 
the TalkBack API documentation at https://thingspeak.com/docs/talkback. 
The REST client implementation is based on the official python Xively API client (SDK).

The tool can be launched as an init.d Linux service with the rpicamtest.sh

TODOs: 
1) Use/enable ThingSpeak TalkBack API
2) Integrate with RasPiConnectServer
3) Use "Automatically reload python module / package on file change" from https://gist.github.com/eberle1080/1013122
and pyinotify module, http://www.saltycrane.com/blog/2010/04/monitoring-filesystem-python-and-pyinotify/
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
TSPK_FILE = 'tspk_keys.txt'
TSPKFEEDUSE = True
TSPKCH_ID   = 9981
TSPKTBUSE  = False
TSPKTB_ID  = 104


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
			
except yaml.YAMLError as e:
	logging.error("Error in configuration file:" % e)
	os._exit()
	
finally:		
	# Add config keys
	dbxConfig['token_file'] = DBTOKEN_FILE
	dbxConfig['image_dir']  = camConfig['image_dir']
	dirConfig['image_dir']  = camConfig['image_dir']
	camConfig['list_size']  = dirConfig['list_size']
	
	# Operation control keys
	timerConfig['enabled']    = True
	camConfig['enabled']   = True
	camConfig['initclass'] = False
	dirConfig['enabled']   = True
	dirConfig['initclass'] = False
	dbxConfig['enabled']   = True
	dbxConfig['initclass'] = False
	
	logging.info("Configuration file read")
	logging.debug("timerConfig: %s" % timerConfig)
	logging.debug("camConfig: %s" % camConfig)
	logging.debug("dirConfig: %s" % dirConfig)
	logging.debug("dbxConfig: %s" % dbxConfig)

### ThingSpeak feed
if TSPKFEEDUSE:
	RESTfeed = thingspk.ThingSpeakAPIClient(TSPKCH_ID, TSPK_FILE)
	logging.info("ThingSpeak channel (%d) initialized" % TSPKCH_ID)
else:
	RESTfeed = None

### Init the ThingSpeak REST feed data
if TSPKFEEDUSE and (RESTfeed is not None):
	RESTfeed.setfield('field1', 0) 
	RESTfeed.setfield('field2', 0) 
	RESTfeed.setfield('field3', 0)
	RESTfeed.setfield('field4', 0)
	rest_update('Init')
						
def rest_update(status_str=None, stream_value=None):
	"""
	ThingSpeak REST API function to upload the feed data. 
	"""
	
	if RESTfeed is not None:
		if status_str is not None: 
			RESTfeed.setfield('status',status_str)
		if stream_value is not None:
			RESTfeed.setfield('field1', stream_value)			
		RESTfeed.update()
		RESTfeed.setfield('status','')

### ThingSpeak TalkBack 
if TSPKTBUSE:
	RESTTalkB = thingspk.ThingSpeakTBClient(TSPKTB_ID, TSPK_FILE)
else:
	RESTTalkB = None
	
###	
### Methods
###
def job_listener(event):
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
		# Increment error counter
		eventsRPi.eventErrcountList[e_jobid] += 1
		
		logging.error("%s: The job crashed!" % e_jobid)
		rest_update("%sCrash" % e_jobid)
	
	elif e_code == EVENT_JOB_EXECUTED:
		#print("%s: The job worked." % e_jobid)

		eventsRPi.eventRuncountList[e_jobid] += 1
		eventsRPi.jobRuncount += 1
		
		if eventsRPi.eventErrList[e_jobid].is_set():
			# Increment error counter
			eventsRPi.eventErrcountList[e_jobid] += 1						
			if eventsRPi.eventErrcountList[e_jobid] > 3:
				#print("%s: too many errors!" % e_jobid)
				status_str = "%sErrorMax: %s" % (e_jobid, time.ctime(time.time))
		
	elif (e_code == EVENT_JOB_ADDED) or (e_code == EVENT_JOB_REMOVED):
		sch_jobs = sched.get_jobs()
		if len(sch_jobs):
			for jb in sch_jobs:
				if not (jb.id == e_jobid):
					if not jb.pending:
						logging.debug("%s (%s): %s" % (jb.id, jb.name, jb.next_run_time))
					else:
						logging.debug("%s (%s): waiting to be added" % (jb.id, jb.name))
			
			status_str = "Jobs: %d" % len(sch_jobs) 
				
		else:
			if not eventsRPi.eventEnd.is_set():
				logging.info("All jobs have been removed!")
				eventsRPi.eventEnd.set()
				status_str = "NoJobs"
	else:
		logging.warning("Unhandled event.code = %s" % e_code)
	 
	### Update REST feed 	
	rest_update(status_str, eventsRPi.eventRuncountList[e_jobid])


def tbk_handler():
	if RESTTalkB is not None:

		RESTTalkB.talkback.execcmd()
		res = RESTTalkB.talkback.response
		if res:
			print("\nRes: %s" % RESTTalkB.talkback.response)
			cmdrx = res.get('command_string')

			# Timer
			if cmdrx==u'tim/01':
				timerConfig['enabled'] = True

			if cmdrx==u'tim/00':
				timerConfig['enabled'] = False


			# Cam
			if cmdrx==u'cam/01':
				camConfig['enabled'] = True
				sched.resume_job(imgCam.name)
				logging.debug("%s is resumed." % imgCam.name)

			if cmdrx==u'cam/00':
				camConfig['enabled'] = False
				sched.pause_job(imgCam.name)
				logging.debug("%s is paused." % imgCam.name)

			if cmdrx==u'cam/02':
				camConfig['initclass'] = True
				logging.debug("%s will be initilized in the next run." % imgCam.name)

			# Dir
			if cmdrx==u'dir/01':
				dirConfig['enabled'] = True
				sched.resume_job(imgDir.name)
				logging.debug("%s is resumed." % imgDir.name)

			if cmdrx==u'dir/00':
				dirConfig['enabled'] = False
				sched.pause_job(imgDir.name)
				logging.debug("%s is paused." % imgDir.name)

			if cmdrx==u'dir/02':
				dirConfig['initclass'] = True


			# Dbx
			if cmdrx==u'dbx/01':
				dbxConfig['enabled'] = True
				sched.resume_job(imgDbx.name)
				logging.debug("%s is resumed." % imgDbx.name)

			if cmdrx==u'dbx/00':
				dbxConfig['enabled'] = False
				sched.pause_job(imgDbx.name)
				logging.debug("%s is paused." % imgDbx.name)

			if cmdrx==u'dbx/02':
				dbxConfig['initclass'] = True

								
### The events
eventsRPi = rpievents.rpiEventsClass(['CAMJob', 'DIRJob', 'DBJob'])
logging.debug(eventsRPi)

### Init the job classes	
imgCam = rpicam.rpiCamClass("CAMJob", camConfig, eventsRPi, RESTfeed) 
logging.info(imgCam)

imgDir = rpimgdir.rpiImageDirClass("DIRJob", dirConfig, imgCam.imageFIFO, eventsRPi, RESTfeed)
logging.info(imgDir)

imgDbx = rpimgdb.rpiImageDbClass("DBXJob", dbxConfig, imgCam.imageFIFO, eventsRPi, RESTfeed)
logging.info(imgDB)


### The APScheduler
sched = BackgroundScheduler(alias='BkgScheduler')
#sched = BlockingScheduler(alias='BlkScheduler')

# Add job execution event handler
sched.add_listener(job_listener, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED | EVENT_JOB_ADDED | EVENT_JOB_REMOVED) 

# Add TalkBack client job; run every 60 seconds
sched.add_job(tbk_handler, 'interval', id="TBJob", seconds=60, misfire_grace_time=10, name='TB' )



### Main loop		
def main():
	"""
	Runs the Scheduler with the Jobs on every day in the set time period.
	"""
	
	# Time period start/stop
	tstart_all = datetime(timerConfig['start_year'], timerConfig['start_month'], timerConfig['start_day'], timerConfig['start_hour'][0], timerConfig['start_min'][0], 0, 0)
	tstop_all  = datetime(timerConfig['stop_year'], timerConfig['stop_month'], timerConfig['stop_day'], timerConfig['stop_hour'][-1], timerConfig['stop_min'][-1], 59, 0)
				
	# Check if the time period is valid
	tnow = datetime.now()
	if tnow >= tstop_all:
		logging.warning("Current time (%s) is after the end of scheduler activity period (%s)!" % (tnow, tstop_all))
		logging.info("Scheduler was not started! Bye!")
		print("Scheduler was not started! Bye!")
		
	else:

		# Start background scheduler
		logging.debug("Scheduler started on: %s" % (time.ctime(time.time())))
		sched.start()

		logging.info("Scheduler will be active in the period: %s - %s" % (tstart_all, tstop_all))
		print("Scheduler will be active in the period: %s - %s" % (tstart_all, tstop_all))
				
		rest_update('Start')
				
		# Enable all day periods
		bValidDayPer = []
		for tper in range(len(timerConfig['start_hour'])):
			bValidDayPer.append(True)
						
		# Check the validity of the periods on the first day (tnow)			
		if tnow >= tstart_all:
			for tper in range(len(timerConfig['start_hour'])):
				if (60*tnow.hour + tnow.minute) >= (60*timerConfig['stop_hour'][tper] + timerConfig['stop_min'][tper]): 
					bValidDayPer[tper] = False	
					logging.info("The daily period %02d:%02d - %02d:%02d was skipped." % (timerConfig['start_hour'][tper], timerConfig['start_min'][tper], timerConfig['stop_hour'][tper], timerConfig['stop_min'][tper]))
				
		# Every day in the given time period
		tcrt = datetime.now()
		while timerConfig['enabled'] and tcrt < tstop_all:
					
			rest_update('BoD')
					
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
					# The jobs will be run only between tstart_per and tstop_per 
					sched.add_job(imgCam.run, 'interval', id=imgCam.name, seconds=camConfig['interval_sec'][tper], start_date=tstart_per, end_date=tstop_per, misfire_grace_time=10, name='CAM' )
					sched.add_job(imgDir.run, 'interval', id=imgDir.name, seconds=dirConfig['dircheck_sec'][tper], start_date=tstart_per+timedelta(minutes=+1), end_date=tstop_per, misfire_grace_time=10, name='DIR' )
					sched.add_job(imgDbx.run, 'interval', id=imgDbx.name, seconds=dbxConfig['dbcheck_sec'][tper], start_date=tstart_per+timedelta(minutes=+2), end_date=tstop_per, misfire_grace_time=10, name='DBX' )
				
					# Main loop
					# The eventsRPi.eventEnd is set when all jobs have been removed/finished
					while not eventsRPi.eventEnd.is_set():
						#time.sleep( camConfig['interval_sec'][tper] )
						
						# Do something else while the scheduler is running
						time.sleep(10)
			
			
				except RuntimeError as e:
					self.eventEnd.set()
					logging.error("RuntimeError: %s! Exiting!" % str(e), exc_info=True)
					raise

				except (KeyboardInterrupt, SystemExit):
					pass
			
				except:
					self.eventEnd.set()
					logging.error("Exception: %s! Exiting!" %  str(sys.exc_info()), exc_info=True)
					raise
		
				finally:			
					time.sleep( 60 )
				
					rest_update('eventEnd')
				
			# Perform the end-of-day maintenance
#			sched.remove_job(imgCam.name)
			imgCam.endDayOAM()
#			sched.remove_job(imgDir.name)
			imgDir.endDayOAM()
#			sched.remove_job(imgDbx.name)
			imgDB.endDayOAM()
			
			# Next day 
			tnow = datetime.now()
			tcrt = datetime(tnow.year, tnow.month, tnow.day, 0, 0, 0, 0) + timedelta(days=1)

			# Enable all day periods
			for tper in range(len(timerConfig['start_hour'])):
				bValidDayPer[tper] = True

			rest_update('EoD')
			
		# End scheduler and exit
		sched.remove_job("TBJob")
		sched.shutdown(wait=True)
		logging.debug("Scheduler stop on: %s" % time.ctime(time.time()))

		if not timerConfig['enabled']:
			logging.info("Scheduler was stopped by external command.")
			rest_update('ExtStop')
		else:
			rest_update('Stop')
				


if __name__ == "__main__":
	main() 
