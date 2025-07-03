set -e

docker build -t ros2_ws .
docker create --name extract ros2_ws
docker cp extract:/ros2_ws/install ./install
docker rm extract
