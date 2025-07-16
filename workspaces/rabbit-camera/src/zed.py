import asyncio
import json
import math
import time

import cv2
import nats
import numpy as np
import pyzed.sl as sl


class ZedCamera:
    image = sl.Mat()
    runtime_params = sl.RuntimeParameters()
    sensors_data = sl.SensorsData()

    def __init__(self, camera_id=0):
        self.zed = sl.Camera()

    def open(self):
        init_params = sl.InitParameters()
        init_params.camera_resolution = sl.RESOLUTION.HD720
        init_params.camera_fps = 30
        init_params.depth_mode = sl.DEPTH_MODE.NONE
        init_params.coordinate_units = sl.UNIT.MILLIMETER
        init_params.sdk_verbose = 1

        status = self.zed.open(init_params)
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
