set -e

docker build -t rabbit-ros2 .
docker create --name extract rabbit-ros2
docker cp extract:/ros2_ws/install ./install
docker rm extract

mkdir -p ../rabbit-power/src/msg
cp ./install/rabbit_interface/lib/python3.12/site-packages/rabbit_interface/msg/_sensor_reading.py ../rabbit-power/src/msg/sensor_reading.py

rm -rf ./install
