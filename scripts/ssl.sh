#!/bin/bash

set -euo pipefail

brew install mkcert
mkcert -install

mkcert -key-file cert/key.key -cert-file cert/cert.crt jetson.rabbit dev.rabbit