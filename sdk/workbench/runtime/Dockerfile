FROM python:3.11-slim
COPY requirements.txt /runner/requirements.txt
RUN pip install --no-cache-dir -r /runner/requirements.txt
RUN mkdir -p /workspace/generated /runner && chmod 755 /workspace /workspace/generated /runner
COPY worker.py /runner/worker.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MPLCONFIGDIR=/tmp/matplotlib IPYTHONDIR=/tmp/ipython JUPYTER_RUNTIME_DIR=/tmp/jupyter
USER 65532:65532
WORKDIR /workspace
ENTRYPOINT ["python", "-I", "/runner/worker.py"]
