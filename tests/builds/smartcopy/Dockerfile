FROM alpine as base-emptybase


FROM alpine as base-smartcopy

COPY --from=default abc /copy1/
COPY --chown=1:2 --from=default xyz /copy2/
COPY ab* /copy3/
{% if user_config.client_type != "podman" %}
# podman escaping works differently (or maybe doesn't work at all?)
COPY --from=default arr[[]0].txt /copy4/
{% endif %}


FROM base-smartcopy as smartcopy

RUN [ "$(ls /copy1/)" == "abc" ]
RUN [ "$(ls /copy2/)" == "xyz" ]
RUN [ "$(ls /copy3/ | sort)" == $'abc\nabd' ]
{% if user_config.client_type != "podman" %}
RUN [ "$(ls /copy4/)" == "arr[0].txt" ]
{% endif %}
