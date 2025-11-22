import subprocess

with open('/home/farshid/.gemini/tmp/57bd0bb4c76ac9c66ea63852ff4f67ac56ff1969fa87aa1c0ed32abf0be314bb/retunnel.log', 'w') as f:
    process = subprocess.Popen(['retunnel', 'http', '11244', '--inspect'], stdout=f, stderr=f)
    process.wait()
