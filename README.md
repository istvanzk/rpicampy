# rpicampy
Time-lapse with Rasberry Pi controlled camera

VER 2.1 for Python 3.4+

Uses APscheduler module to background schedule three interval jobs: 
1. rpicam:		Run and control a:
				- Raspberry PI camera using using the picamera module, or
				- Raspberry PI camera using the raspistill utility, or 
				- USB web camera using fswebcam utility 
2. rpimgdir:	Manage the set of saved images by rpiCam.  
3. rpimgdb:		Manage images in a remote directory (dropbox).

The configuration parameters are read from the rpiconfig.yaml

The tool can be launched as an init.d Linux service with the rpicamtest.sh
