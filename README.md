# rpicampy
Time-lapse with Rasberry Pi controlled camera.

Version 4.5 for Python 3.4+


rpibase:	Base class for rpicam, rpimgdir and rpimgdb

rpicam:		Run and control a:

	- Raspberry PI camera using using the picamera module, or

	- Raspberry PI camera using the raspistill utility, or 

	- USB web camera using fswebcam utility 

rpimgdir:	Manage the set of saved images by rpiCam.  

rpimgdb:	Manage images in a remote directory (Dropbox SDK, API V2, Python 3.4).

rpievents:	Implements the the set of events and counters to be used in the rpi jobs.

rpififo:	Implements the a FIFO buffer for the image file names (full path) generated in the rpicam job.

thingspk:	A simple REST request abstraction layer and a light ThingSpeak API and TalkBack App SDK. 

rpicam_sch:	The main method. Uses APScheduler (Advanced Python Scheduler: http://apscheduler.readthedocs.org/en/latest/) 
to background schedule three interval jobs implemented in: rpicam, rpimgdir and rpimgdb. An additional ThingSpeak TalkBack job is also scheduled.

rpiconfig.yaml:	The configuration parameters.

The image file names are:  '%d%m%y-%H%M%S-CAMX.jpg', where CAMX is the camera identification (ID string).
The images are saved locally and remotely in a sub-folder. The sub-folders name is the current date '%d%m%y'.

The rpicam module implements an 'dark' time image exposure algorithm. 
A 'dark' time period (start and stop) can be configured manually using the hour/min parameters set in the configuration file.
Alternatively, the 'dark' time period can be configured automatically using the PyEphem module (http://rhodesmill.org/pyephem/) 
and the location parameters (latitude and longitude) set in the configuration file.


The implementation of the thingspk module follows the ThingSpeak API documentation at https://www.mathworks.com/help/thingspeak/
and the TalkBack API documentation at https://www.mathworks.com/help/thingspeak/talkback-app.html
The REST client implementation follows the model of the official python Xively API client (SDK).

The tool can be launched as an init.d Linux service with the rpicamtest.sh
