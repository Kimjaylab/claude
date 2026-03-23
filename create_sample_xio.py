"""샘플 XIO 파일(zip) 생성 - 테스트용"""
import zipfile
import io

INERTIAL = """\
Time (s),Gyroscope X (deg/s),Gyroscope Y (deg/s),Gyroscope Z (deg/s),Accelerometer X (g),Accelerometer Y (g),Accelerometer Z (g)
0.0,0.12,-0.34,1.02,0.01,-0.02,1.00
0.01,0.15,-0.30,0.98,0.01,-0.01,1.00
3661.5,0.20,-0.25,1.10,0.02,-0.01,0.99
"""

QUATERNION = """\
Time (s),W,X,Y,Z
0.0,0.9998,0.0012,-0.0034,0.0056
0.01,0.9997,0.0013,-0.0033,0.0057
3661.5,0.9995,0.0015,-0.0030,0.0060
"""

EULER = """\
Time (s),Roll (deg),Pitch (deg),Yaw (deg)
0.0,0.23,-0.45,12.34
0.01,0.24,-0.44,12.35
3661.5,0.30,-0.40,13.00
"""

with zipfile.ZipFile("sample.xio", "w") as zf:
    zf.writestr("Inertial.csv", INERTIAL)
    zf.writestr("Quaternion.csv", QUATERNION)
    zf.writestr("EulerAngles.csv", EULER)

print("sample.xio 생성 완료")
