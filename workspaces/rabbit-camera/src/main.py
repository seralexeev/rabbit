import asyncio

import cv2
import nats
import numpy as np
import pyzed.sl as sl


async def main():
    nc = await nats.connect(
        "nats://nats:4222",
        name="rabbit-camera",
        ping_interval=5,
        max_reconnect_attempts=-1,
        reconnect_time_wait=2,
    )

    zed = sl.Camera()

    init_params = sl.InitParameters()
    init_params.camera_resolution = sl.RESOLUTION.HD720
    init_params.camera_fps = 30
    init_params.depth_mode = sl.DEPTH_MODE.NONE
    init_params.coordinate_units = sl.UNIT.MILLIMETER
    init_params.sdk_verbose = 1

    status = zed.open(init_params)
    if status != sl.ERROR_CODE.SUCCESS:
        raise RuntimeError(f"ZED camera initialization failed: {status}")

    image = sl.Mat()
    sensors_data = sl.SensorsData()
    runtime_params = sl.RuntimeParameters()

    while True:
        try:
            if zed.grab(runtime_params) == sl.ERROR_CODE.SUCCESS:
                zed.retrieve_image(image, sl.VIEW.RIGHT)

                # Данные сенсоров
                zed.get_sensors_data(sensors_data, sl.TIME_REFERENCE.IMAGE)

                # IMU данные
                imu_data = sensors_data.get_imu_data()
                if imu_data.is_available:
                    accel = imu_data.get_linear_acceleration()
                    gyro = imu_data.get_angular_velocity()
                    orientation = imu_data.get_pose().get_orientation()
                    
                    print(f"Акселерометр: [{accel[0]:.3f}, {accel[1]:.3f}, {accel[2]:.3f}] m/s²")
                    print(f"Гироскоп: [{gyro[0]:.3f}, {gyro[1]:.3f}, {gyro[2]:.3f}] rad/s")
                    print(f"Ориентация (кватернион): [{orientation[0]:.3f}, {orientation[1]:.3f}, {orientation[2]:.3f}, {orientation[3]:.3f}]")
                
                # Барометр
                barometer_data = sensors_data.get_barometer_data()
                if barometer_data.is_available:
                    print(f"Давление: {barometer_data.pressure:.2f} hPa")
                    print(f"Относительная высота: {barometer_data.relative_altitude:.2f} м")
                
                # Магнетометр
                magnetometer_data = sensors_data.get_magnetometer_data()
                if magnetometer_data.is_available:
                    mag_field = magnetometer_data.get_magnetic_field_calibrated()
                    print(f"Магнитное поле: [{mag_field[0]:.3f}, {mag_field[1]:.3f}, {mag_field[2]:.3f}] μT")
                
                # Температура - правильный способ
                try:
                    # Температура IMU
                    temp_imu = sensors_data.get_temperature_data(sl.SENSOR_LOCATION.IMU)
                    if temp_imu.is_available:
                        print(f"Температура IMU: {temp_imu.temperature:.1f}°C")
                    
                    # Температура барометра  
                    temp_baro = sensors_data.get_temperature_data(sl.SENSOR_LOCATION.BAROMETER)
                    if temp_baro.is_available:
                        print(f"Температура барометра: {temp_baro.temperature:.1f}°C")
                except Exception as e:
                # Альтернативный способ для старых версий SDK
                    try:
                        temperature_map = sensors_data.get_temperature_data()
                        if sl.SENSOR_LOCATION.IMU in temperature_map:
                            print(f"Температура IMU: {temperature_map[sl.SENSOR_LOCATION.IMU]:.1f}°C")
                        if sl.SENSOR_LOCATION.BAROMETER in temperature_map:
                            print(f"Температура барометра: {temperature_map[sl.SENSOR_LOCATION.BAROMETER]:.1f}°C")
                    except:
                        print("Температурные данные недоступны")
                
                print("---")

                frame = image.get_data()
                frame_rgb = frame[:, :, :3]

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
                await nc.flush()

            else:
                raise RuntimeError("Failed to grab frame from ZED camera")

        except RuntimeError as e:
            print(f"Something went wrong: {e}")
            await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("Exiting...")
            break

    zed.close()
    await nc.close()


if __name__ == "__main__":
    asyncio.run(main())
