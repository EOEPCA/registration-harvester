# Basis-Image verwenden
FROM python:3.11-slim

# Any python libraries that require system libraries to be installed will likely
# need the following packages in order to build
RUN apt-get update && \
    apt-get -y upgrade && \
    apt-get install -y build-essential git && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /code

COPY ./worker /code/app
COPY ./README.md /code/app/README.md
COPY ./LICENSE /code/app/LICENSE
COPY ./etc /code/etc

RUN python -m pip install --no-cache-dir --upgrade /code/app

CMD ["fastapi", "run", "app/main.py", "--port", "8080"]
