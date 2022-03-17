FROM python:{{ python_version }} AS base-tplbuild
PUSHCONTEXT base

COPY --from=docker:dind /usr/local/bin/docker /bin/

WORKDIR /tplbuild

COPY . ./

# TODO: use setuptools instead of requirements files
RUN pip install -r requirements.txt {% if env == "dev" -%}-r requirements-dev.txt{%- endif %}


FROM base-tplbuild AS tplbuild

COPY . ./

RUN echo hi qemu

ENV PYTHONPATH="${PYTHONPATH}:/tplbuild"
ENTRYPOINT ["python3", "-m", "tplbuild"]
