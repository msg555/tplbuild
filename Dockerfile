FROM docker.io/library/python:{{ vars.python_version }} AS base-tplbuild

RUN apt update \
 && apt install -y podman \
 && rm -rf /var/lib/apt/lists/*

COPY --from=docker.io/library/docker:dind /usr/local/bin/docker /bin/

WORKDIR /tplbuild

{% if vars.env == "dev" -%}
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements.txt -r requirements-dev.txt
{% else -%}
COPY requirements.txt ./
RUN pip install -r requirements.txt
{% endif %}


FROM base-tplbuild AS tplbuild

COPY . ./

ENV PYTHONPATH="${PYTHONPATH}:/tplbuild"
ENTRYPOINT ["python3", "-m", "tplbuild"]
