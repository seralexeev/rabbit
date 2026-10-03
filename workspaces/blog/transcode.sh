#!/bin/bash

set -e

if [ -z "$1" ]; then
  echo "Usage: $0 <name>"
  exit 1
fi

NAME="$1"

echo "Transcoding $NAME"

ffmpeg -hide_banner -i "static/media/$NAME" \
 -c:v libx264 -profile:v high -level 4.1 -pix_fmt yuv420p \
 -preset veryfast -crf 20 \
 -c:a aac -b:a 192k \
 -movflags +faststart \
 "static/media/$NAME.mp4"

 rm "static/media/$NAME"