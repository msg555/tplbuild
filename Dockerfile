FROM docker.io/library/python:{{ python_version }} AS base-tplbuild

RUN apt update \
 && apt install -y podman \
 && rm -rf /var/lib/apt/lists/*

COPY --from=docker.io/library/docker:dind /usr/local/bin/docker /bin/

WORKDIR /tplbuild

COPY --from=base . ./

RUN pip install -r requirements.txt {% if env == "dev" -%}-r requirements-dev.txt{%- endif %}


FROM base-tplbuild AS tplbuild

COPY . ./

RUN echo hi qemu

ENV PYTHONPATH="${PYTHONPATH}:/tplbuild"
ENTRYPOINT ["python3", "-m", "tplbuild"]
