# rpicampy
Time-lapse with Rasberry Pi controlled camera.

Version 3.0 for Python 3.4+

Uses APScheduler (Advanced Python Scheduler: http://pythonhosted.org/APScheduler/) to background schedule three interval jobs: 

1. rpicam:		Run and control a:

				- Raspberry PI camera using using the picamera module, or

				- Raspberry PI camera using the raspistill utility, or 

				- USB web camera using fswebcam utility 

2. rpimgdir:	Manage the set of saved images by rpiCam.  

3. rpimgdb:		Manage images in a remote directory (Dropbox SDK, API V2, Python 3.4).

The configuration parameters are read from the rpiconfig.yaml

The image file names are:  '%d%m%y-%H%M%S-CAMX.jpg', where X is the camera number (ID string).
The images are saved locally and remotely in a sub-folder. The sub-folder name is the current date '%d%m%y'

A simple REST request abstraction layer and a light ThingSpeak API SDK is provided in the thingspeak module.
The implementation follows to the API documentation at http://community.thingspeak.com/documentation/api/
and the TalkBack API documentation at https://thingspeak.com/docs/talkback
The REST client implementation follows the model of the official python Xively API client (SDK).

The tool can be launched as an init.d Linux service with the rpicamtest.sh
