set -e

docker build -t nvblox_test .
docker run --rm -v .:/rabbit nvblox_test /bin/bash -c "pytest -s /rabbit/src/nvblox_torch"