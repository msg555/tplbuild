FROM python:3.10 AS base-my-app

RUN apt update \
 && apt install -y default-mysql-client

COPY requirements.txt /tmp/
RUN cd /tmp && pip install -r requirements.txt

{% if vars.install_dev_packages %}
RUN apt update \
 && apt install -y vim
{% endif %}


FROM base-my-app AS my-app

WORKDIR /my-app

COPY . .

EXPOSE 8080

CMD ["uvicorn", "my_app.app:make_app", {% if profile == "dev" %}"--reload", {% endif %}"--factory", "--port=8080", "--host=0"]
