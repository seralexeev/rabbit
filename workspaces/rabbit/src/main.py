import threading
import time
import signal
import sys
from evdev import InputDevice, ecodes
from roboclaw import Roboclaw
from board import SCL, SDA
import busio
from adafruit_pca9685 import PCA9685


class Servo:
    def __init__(self, channel, min_pulse=450, max_pulse=1100):
        i2c = busio.I2C(SCL, SDA)
        self.pca = PCA9685(i2c)
        self.pca.frequency = 50
        self.channel = channel
        self.min_pulse = min_pulse
        self.max_pulse = max_pulse

    # angle between -1 and 1
    def set_angle(self, angle):
        angle = max(min(angle, 1), -1)
        value = self.min_pulse + (self.max_pulse - self.min_pulse) * (angle + 1) / 2
        print(f"Setting servo angle: {angle}, Pulse length: {value} us")

        pulse_length_s = value / 1_000_000
        duty_cycle = int(pulse_length_s * self.pca.frequency * 65536)
        self.pca.channels[self.channel].duty_cycle = duty_cycle


class RabbitRoboclaw:
    def __init__(self, device_path, baud_rate=115200, address=0x80):
        self.device_path = device_path
        self.baud_rate = baud_rate
        self.address = address
        self.rc = None
        self.is_connected = False
        # To handle wrong wire connection
        self.direction_modifier = -1
        self.max_duty = 32767 
        self.min_duty = -32767

    def connect(self):
        try:
            self.rc = Roboclaw(self.device_path, self.baud_rate)
            self.rc.Open()

            result = self.rc.ReadVersion(self.address)

            if result[0] and len(result) > 1:
                print(f"🟢 Roboclaw connected: {result[1]}")
                self.is_connected = True
                return True
            else:
                print("🔴 Failed to connect to Roboclaw")
                return False
        except Exception as e:
            print(f"Error connecting to Roboclaw: {e}")
            return False

    def set_motor_duty(self, m1_duty, m2_duty):
        print(f"Setting motor duty: M1={m1_duty}, M2={m2_duty}")

        if not self.is_connected or not self.rc:
            print("🔴 Roboclaw not connected")
            return False
        try:
            self.rc.DutyM1(self.address, m1_duty)
            self.rc.DutyM2(self.address, m2_duty)
            return True
        except Exception as e:
            print(f"Error setting motor duty: {e}")
            return False

    def stop_motors(self):
        return self.set_motor_duty(0, 0)

    def read_version(self):
        if not self.is_connected or not self.rc:
            return False
        try:
            result = self.rc.ReadVersion(self.address)
            return result[0]
        except:
            return False

    def disconnect(self):
        if self.rc:
            try:
                self.stop_motors()
                print("Motors stopped")
            except:
                pass
        self.is_connected = False
        print("Roboclaw disconnected")


class RabbitGamepad:
    def __init__(self, device_path, shutdown_event=None):
        self.device_path = device_path
        self.device = None
        self.state = {"left_stick_x": 128, "r2": 0, "l2": 0}
        self.shutdown_event = shutdown_event
        self.is_connected = False

    def connect(self):
        try:
            self.device = InputDevice(self.device_path)
            print(f"🟢 Gamepad connected: {self.device.name}")
            self.is_connected = True
            return True
        except Exception as e:
            print(f"🔴 Error connecting gamepad: {e}")
            return False

    def read_input(self):
        if not self.device or not self.is_connected:
            return
        try:
            for event in self.device.read_loop():
                if self.shutdown_event and self.shutdown_event.is_set():
                    break
                if event.type == ecodes.EV_ABS:
                    if event.code == ecodes.ABS_X:
                        self.state["left_stick_x"] = event.value
                    elif event.code == ecodes.ABS_RZ:
                        self.state["r2"] = event.value / 255
                    elif event.code == ecodes.ABS_Z:
                        self.state["l2"] = event.value / 255
                    
        except Exception as e:
            print(f"🔴 Error in read_gamepad: {e}")
        finally:
            print("⚪ Gamepad reading stopped")

    def get_state(self):
        return self.state.copy()

    def disconnect(self):
        self.is_connected = False
        print("⚪ Gamepad disconnected")


class Rabbit:
    def __init__(self):
        self.shutdown_event = threading.Event()
        self.gamepad = RabbitGamepad("/dev/joy", self.shutdown_event)
        self.roboclaw = RabbitRoboclaw("/dev/roboclaw")
        self.servo = Servo(channel=0)

    def control_robot(self):
        self.servo.set_angle(0)

        if not self.roboclaw.connect():
            return

        try:
            while True:
                if self.shutdown_event.is_set():
                    break

                gamepad_state = self.gamepad.get_state()

                # motors
                l2_value = max(min(gamepad_state["l2"], 1), 0)
                r2_value = max(min(gamepad_state["r2"], 1), 0)
                value = r2_value - l2_value

                speed = max(
                    min(int(value * 32767), self.roboclaw.max_duty),
                    self.roboclaw.min_duty,
                )

                print(f"Gamepad state: {gamepad_state}, Speed: {speed}")

                self.roboclaw.set_motor_duty(
                    speed * self.roboclaw.direction_modifier,
                    speed * self.roboclaw.direction_modifier,
                )

                # servo
                left_stick_x = gamepad_state["left_stick_x"]
                angle = (left_stick_x - 128) / 128  # Normalize to -1 to 1
                self.servo.set_angle(angle)

                time.sleep(0.01)

        except Exception as e:
            print(f"Error in control_robot: {e}")
        finally:
            self.roboclaw.disconnect()

    def start(self):
        if not self.gamepad.connect():
            return False

        gamepad_thread = threading.Thread(target=self.gamepad.read_input, daemon=False)
        control_thread = threading.Thread(target=self.control_robot, daemon=False)

        gamepad_thread.start()
        control_thread.start()

        return gamepad_thread, control_thread

    def stop(self):
        self.shutdown_event.set()
        self.gamepad.disconnect()
        self.roboclaw.disconnect()


def signal_handler(_, __):
    print("\nSignal received. Stopping...")
    rabbit.stop()


def run():
    global rabbit
    rabbit = Rabbit()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    threads = rabbit.start()
    if not threads:
        print("🔴 Unable to start threads. Exiting...")
        return

    gamepad_thread, control_thread = threads

    try:
        rabbit.shutdown_event.wait()
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt received. Stopping...")
        rabbit.stop()

    print("Waiting for threads to finish...")
    gamepad_thread.join(timeout=2)
    control_thread.join(timeout=2)

    print("All threads finished. Exiting...")


if __name__ == "__main__":
    run()
