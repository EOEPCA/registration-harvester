FROM python:3.12-slim

# Any python libraries that require system libraries to be installed will likely
# need the following packages in order to build
RUN apt-get update && \
    apt-get -y upgrade && \
    apt-get install -y build-essential git && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /harvester
COPY . /harvester
RUN python -m pip install --no-cache-dir --upgrade /harvester

CMD ["fastapi", "run", "src/harvester/main.py", "--port", "8080"]