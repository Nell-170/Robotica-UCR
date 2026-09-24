from naoqi import ALProxy
tts = ALProxy("ALTextToSpeech", "192.168.1.140", 9559)
tts.say("Python also works")