# rpicampy
Time-lapse with Rasberry Pi controlled camera.

GAMMA version 2.1 for Python 3.4+

Uses APScheduler (Advanced Python Scheduler: http://pythonhosted.org/APScheduler/) to background schedule three interval jobs: 

1. rpicam:		Run and control a:

				- Raspberry PI camera using using the picamera module, or

				- Raspberry PI camera using the raspistill utility, or 

				- USB web camera using fswebcam utility 

2. rpimgdir:	Manage the set of saved images by rpiCam.  

3. rpimgdb:		Manage images in a remote directory (Dropbox SDK, API V2, Python 3.4).

The configuration parameters are read from the rpiconfig.yaml

A simple REST request abstraction layer and a light ThingSpeak API SDK is provided in the thingspeak module.
The implementation follows to the API documentation at http://community.thingspeak.com/documentation/api/
and the TalkBack API documentation at https://thingspeak.com/docs/talkback
The REST client implementation is based on the official python Xively API client (SDK).

The tool can be launched as an init.d Linux service with the rpicamtest.sh