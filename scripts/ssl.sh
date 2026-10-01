#!/bin/bash

set -euo pipefail

brew install mkcert
mkcert -install

mkcert -key-file cert/key.pem -cert-file cert/cert.pem jetson.rabbit dev.rabbit localhost