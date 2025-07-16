FROM stereolabs/zed:4.2-py-runtime-jetson-jp6.0.0

RUN python3 -m pip install nats-py

WORKDIR /rabbit
COPY src/ src/

CMD ["python3", "-u", "src/main.py"]
