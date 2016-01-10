#!/usr/local/bin/python3.4
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

Uses APScheduler (Advanced Python Scheduler: http://pythonhosted.org/APScheduler/) 
to background schedule three interval jobs: 
	1. rpicam:		Run and control a:
					- Raspberry PI camera using using the picamera module, or
					- Raspberry PI camera using the raspistill utility, or 
					- USB web camera using fswebcam utility 
	2. rpimgdir:	Manage the set of saved images by rpiCam.  
	3. rpimgdb:		Manage images in a remote directory (Dropbox SDK, API V2, Python 3.4).
The configuration parameters are read from the rpiconfig.yaml

TODO: 
1) Loop over the defined periods per day
2) Integrate with RasPiConnectServer
3) Use ThingSpeak TalkBack
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

### Running mode
DAILYPER = True

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
					level=logging.DEBUG,
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
		timerConfig, camImgConfig, dirImgConfig, dbImgConfig = yaml.load_all(stream)
		
	dbImgConfig['token_file'] = DBTOKEN_FILE
	dbImgConfig['image_dir'] = camImgConfig['image_dir']
	dirImgConfig['image_dir'] = camImgConfig['image_dir']
	camImgConfig['list_size'] = dirImgConfig['list_size']
	
	logging.info("Configuration file read")
	logging.debug("timerConfig: %s" % timerConfig)
	logging.debug("camImgConfig: %s" % camImgConfig)
	logging.debug("dirImgConfig: %s" % dirImgConfig)
	logging.debug("dbImgConfig: %s" % dbImgConfig)
	
except yaml.YAMLError as e:
	logging.error("Error in configuration file:" % e)
	os._exit()
		

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
	RESTfeed.setfield('status','Start')
	RESTfeed.update()	
	RESTfeed.setfield('status','')
		
			
def rest_update(stream_value=None, status_str=None):
	"""
	ThingSpeak REST API function to upload the feed data. 
	"""
	
	if RESTfeed is not None:
		if stream_value is not None:
			RESTfeed.setfield('field1', stream_value)
		if status_str is not None: 
			RESTfeed.setfield('status',status_str)
		RESTfeed.update()

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
				status_str = "Stop"
	else:
		logging.warning("Unhandled event.code = %s" % e_code)
	 
	### Update REST feed 	
	rest_update(eventsRPi.eventRuncountList[e_jobid], status_str)

								
### The events
eventsRPi = rpievents.rpiEventsClass(['CAMJob', 'DIRJob', 'DBJob'])
logging.debug(eventsRPi)

### Init the job classes	
webCam = rpicam.rpiCamClass("CAMJob", camImgConfig, eventsRPi, RESTfeed) 
logging.info(webCam)

imgDir = rpimgdir.rpiImageDirClass("DIRJob", dirImgConfig, webCam.imageFIFO, eventsRPi, RESTfeed)
logging.info(imgDir)

imgDB = rpimgdb.rpiImageDbClass("DBJob", dbImgConfig, webCam.imageFIFO, eventsRPi, RESTfeed)
logging.info(imgDB)

### The APScheduler
sched = BackgroundScheduler(alias='BkgScheduler')
#sched = BlockingScheduler(alias='BlkScheduler')

### Add job execution event handler
sched.add_listener(job_listener, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED | EVENT_JOB_ADDED | EVENT_JOB_REMOVED) 
		
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
		#logging.info("Jobs to be run every day at: %02d:%02d:00" % (start_hour, start_min))
				
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
					# The jobs will be run only between tstart_per and tstop_per 
					sched.add_job(webCam.run, 'interval', id=webCam.name, seconds=camImgConfig['interval_sec'][tper], start_date=tstart_per, end_date=tstop_per, misfire_grace_time=10, name='CAM' )
					sched.add_job(imgDir.run, 'interval', id=imgDir.name, seconds=dirImgConfig['dircheck_sec'][tper], start_date=tstart_per+timedelta(minutes=+1), end_date=tstop_per, misfire_grace_time=10, name='DIR' )
					sched.add_job(imgDB.run, 'interval', id=imgDB.name, seconds=dbImgConfig['dbcheck_sec'][tper], start_date=tstart_per+timedelta(minutes=+2), end_date=tstop_per, misfire_grace_time=10, name='DB' )
				
					# Start scheduler
					#logging.debug("Scheduler start on: %s" % (time.ctime(time.time())))
					#sched.start()
				
					# Main loop
					# The eventsRPi.eventEnd is set when all jobs have been removed/finished
					while not eventsRPi.eventEnd.is_set():
						time.sleep( camImgConfig['interval_sec'][tper] )
						
						# Do something else while the scheduler is running
					
					# TODO:		
					# Use rest_update(status_str)	
			
			
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
					# End scheduler
					# This will still shut down the job stores and executors and wait 
					# for any running jobs to complete
					time.sleep( 10 )
					#sched.shutdown(wait=True)
					#logging.debug("Scheduler stop on: %s" % time.ctime(time.time()))
				
			# Perform the end-of-day maintenance
#			sched.remove_job(webCam.name)
			webCam.endDayOAM()
#			sched.remove_job(webDir.name)
			imgDir.endDayOAM()
#			sched.remove_job(webDB.name)
			if CAMID == 'CAM1':
				imgDB.endDayOAM()
			
			# Next day 
			tnow = datetime.now()
			tcrt = datetime(tnow.year, tnow.month, tnow.day, 0, 0, 0, 0) + timedelta(days=1)

			# Enable all day periods
			for tper in range(len(timerConfig['start_hour'])):
				bValidDayPer[tper] = True


		# End scheduler
		sched.shutdown(wait=True)
		logging.debug("Scheduler stop on: %s" % time.ctime(time.time()))


if __name__ == "__main__":
	main() 
