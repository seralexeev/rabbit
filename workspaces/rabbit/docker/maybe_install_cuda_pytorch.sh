#!/bin/bash

# On aarch64, the default pytorch wheels does not support CUDA. We therefore install custom versions.
# See https://forums.developer.nvidia.com/t/pytorch-for-jetson/72048 for more wheels.
set -e
if [ $SKIP_PYTORCH_INSTALL -eq 0 ]; then
    echo "Installing pytorch"
    . /opt/venv/bin/activate
    python3 -m pip install --ignore-installed --upgrade pip
    wget https://nvidia.box.com/shared/static/mp164asf3sceb570wvjsrezk1p4ftj8t.whl -O  /torch-2.3.0-cp310-cp310-linux_aarch64.whl
    pip install /torch-2.3.0-cp310-cp310-linux_aarch64.whl
    rm /torch-2.3.0-cp310-cp310-linux_aarch64.whl
    wget https://nvidia.box.com/shared/static/xpr06qe6ql3l6rj22cu3c45tz1wzi36p.whl -O /torchvision-0.18.0-cp310-cp310-linux_aarch64.whl
    pip install /torchvision-0.18.0-cp310-cp310-linux_aarch64.whl
    rm /torchvision-0.18.0-cp310-cp310-linux_aarch64.whl
else
    echo "Skipping pytorch installation"
fi
