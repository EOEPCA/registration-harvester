FROM python:3.12-slim

# Any python libraries that require system libraries to be installed will likely
# need the following packages in order to build
RUN apt-get update && \
    apt-get -y upgrade && \
    apt-get install -y build-essential git && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /worker
COPY . /worker
RUN python -m pip install --no-cache-dir --upgrade /worker

CMD ["fastapi", "run", "src/worker/main.py", "--port", "8080"]