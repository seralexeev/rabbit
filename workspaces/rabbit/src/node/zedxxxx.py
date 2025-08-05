import asyncio
import json
import sys
import zlib

import cv2
import nats
import numpy as np

sys.path.append("/usr/local/lib/python3.10/dist-packages")

import pyzed.sl as sl


class ZedCamera:
    image = sl.Mat()
    runtime_params = sl.RuntimeParameters()
    sensors_data = sl.SensorsData()
    res = sl.Resolution(
        width=320,
        height=240,
    )

    init_params = sl.InitParameters(
        camera_resolution=sl.RESOLUTION.HD720,
        camera_fps=30,
        depth_mode=sl.DEPTH_MODE.NEURAL,
        coordinate_units=sl.UNIT.METER,
        coordinate_system=sl.COORDINATE_SYSTEM.RIGHT_HANDED_Y_UP,
        sdk_verbose=1,
    )

    def __init__(self):
        self.zed = sl.Camera()
        self.point_cloud = sl.Mat(
            self.res.width, self.res.height, sl.MAT_TYPE.F32_C4, sl.MEM.CPU
        )

    def open(self):
        status = self.zed.open(self.init_params)
        if status != sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f"ZED camera initialization failed: {status}")

        info = self.zed.get_camera_information()
        print(f"Camera model: {info.camera_model}")
        print(f"Serial Number: {info.serial_number}")
        print(f"Camera Firmware: {info.camera_configuration.firmware_version}")
        print(f"Sensors Firmware: {info.sensors_configuration.firmware_version}")

    def capture_frame(self):
        if self.zed.grab(self.runtime_params) != sl.ERROR_CODE.SUCCESS:
            raise RuntimeError("Failed to grab image from ZED camera")

        self.zed.retrieve_image(self.image, sl.VIEW.RIGHT)
        frame = self.image.get_data()
        frame_rgb = frame[:, :, :3]

        return frame_rgb

    def retrieve_measure(self):
        self.zed.retrieve_measure(
            self.point_cloud, sl.MEASURE.XYZ, sl.MEM.CPU, self.res
        )

        return self.point_cloud

    def get_sensors_data(self):
        self.zed.get_sensors_data(self.sensors_data, sl.TIME_REFERENCE.IMAGE)

        imu_data = self.sensors_data.get_imu_data()
        barometer_data = self.sensors_data.get_barometer_data()
        magnetometer_data = self.sensors_data.get_magnetometer_data()
        temperature_data = self.sensors_data.get_temperature_data()

        linear_acceleration = imu_data.get_linear_acceleration()
        angular_velocity = imu_data.get_angular_velocity()

        pressure = barometer_data.pressure
        relative_altitude = barometer_data.relative_altitude

        magnetic_field = magnetometer_data.get_magnetic_field_uncalibrated()

        imu = {
            "linear_acceleration": {
                "x": linear_acceleration[0],
                "y": linear_acceleration[1],
                "z": linear_acceleration[2],
            },
            "angular_velocity": {
                "x": angular_velocity[0],
                "y": angular_velocity[1],
                "z": angular_velocity[2],
            },
        }

        other = {
            "temperature": {
                "imu": temperature_data.get(sl.SENSOR_LOCATION.IMU),
                "barometer": temperature_data.get(sl.SENSOR_LOCATION.BAROMETER),
                "onboard_left": temperature_data.get(sl.SENSOR_LOCATION.ONBOARD_LEFT),
                "onboard_right": temperature_data.get(sl.SENSOR_LOCATION.ONBOARD_RIGHT),
            },
            "barometer": {
                "pressure": pressure,
                "relative_altitude": relative_altitude,
            },
            "magnetometer": {
                "magnetic_heading": magnetometer_data.magnetic_heading,
                "magnetic_field": {
                    "x": magnetic_field[0],
                    "y": magnetic_field[1],
                    "z": magnetic_field[2],
                },
            },
        }

        return imu, other

    def close(self):
        self.zed.close()


async def main():
    nc = await nats.connect(
        "nats://nats:4222",
        name="rabbit-zed",
        ping_interval=5,
        max_reconnect_attempts=-1,
        reconnect_time_wait=2,
    )

    zed = ZedCamera()
    zed.open()
    frame = 0

    while True:
        try:
            frame_rgb = zed.capture_frame()
            success, buffer = cv2.imencode(
                ".jpg", frame_rgb, [cv2.IMWRITE_JPEG_QUALITY, 75]
            )

            if not success:
                raise RuntimeError("Failed to encode image")

            await nc.publish(
                "rabbit.camera.frame",
                buffer.tobytes(),
                headers={
                    "type": "image/jpg",
                    "width": str(frame_rgb.shape[1]),
                    "height": str(frame_rgb.shape[0]),
                },
            )

            imu, other = zed.get_sensors_data()

            await nc.publish(
                "rabbit.camera.imu",
                json.dumps(imu).encode(),
                headers={
                    "type": "application/json",
                },
            )

            arr = zed.retrieve_measure().get_data()
            compressed = zlib.compress(arr.tobytes(), level=6)

            await nc.publish(
                "rabbit.camera.point_cloud",
                compressed,
                headers={
                    "type": "application/json",
                    "shape": json.dumps(arr.shape),
                },
            )

            if frame % 30 == 0:
                await nc.publish(
                    "rabbit.camera.sensor",
                    json.dumps(other).encode(),
                    headers={
                        "type": "application/json",
                    },
                )

            frame += 1
            await nc.flush()

        except KeyboardInterrupt:
            print("Exiting...")
            break

    zed.close()
    await nc.close()


if __name__ == "__main__":
    asyncio.run(main())
