from naoqi import ALProxy


def get_naoqi_version(robotIP, PORT=9559):
  try:
    systemProxy = ALProxy('ALSystem', robotIP, PORT)
    version = systemProxy.systemVersion()
    print(f'Version de NAOqi: {version}')
  except Exception as e:
    print(f'Error al conectar: {e}')
    
get_naoqi_version('192.168.1.140')
