from naoqi import ALProxy
motion = ALProxy("ALMotion", "192.168.1.140", 9559)
tts = ALProxy("ALTextToSpeech", "192.168.1.140", 9559)
motion.moveInit()
motion.post.moveTo(0.5, 0, 0)
tts.say("I'm walking")