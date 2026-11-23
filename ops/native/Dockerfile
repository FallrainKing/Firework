FROM python:3.12-slim
RUN groupadd -g 1000 agent && useradd -m -u 1000 -g 1000 agent
COPY ops/native/entry.py /opt/firework/entry.py
USER 1000:1000
WORKDIR /workspace
ENTRYPOINT ["python3", "/opt/firework/entry.py"]
