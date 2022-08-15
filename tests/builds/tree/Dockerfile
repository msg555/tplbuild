FROM alpine AS base-a
WORKDIR /files
RUN touch a \
 && [ "$(find -type f | sort)" == $'./a' ]

FROM base-a AS base-aa
RUN touch aa \
 && find -type f | sort \
 && [ "$(find -type f | sort)" == $'./a\n./aa' ]

FROM base-a AS base-ab
RUN touch ab \
 && [ "$(find -type f | sort)" == $'./a\n./ab' ]

FROM base-aa AS base-aaa
RUN touch aaa \
 && [ "$(find -type f | sort)" == $'./a\n./aa\n./aaa' ]

FROM base-aa AS base-aab
RUN touch aab \
 && [ "$(find -type f | sort)" == $'./a\n./aa\n./aab' ]

FROM alpine AS top-a
WORKDIR /base-files
COPY --from=base-a /files a/
COPY --from=base-aa /files aa/
COPY --from=base-ab /files ab/
COPY --from=base-aaa /files aaa/
COPY --from=base-aab /files aab/
RUN [ "$(find -type f | sort)" == $'./a/a\n./aa/a\n./aa/aa\n./aaa/a\n./aaa/aa\n./aaa/aaa\n./aab/a\n./aab/aa\n./aab/aab\n./ab/a\n./ab/ab' ]

WORKDIR /files
RUN touch a \
 && [ "$(find -type f | sort)" == $'./a' ]

FROM top-a AS top-aa
RUN touch aa \
 && find -type f | sort \
 && [ "$(find -type f | sort)" == $'./a\n./aa' ]

FROM top-a AS top-ab
RUN touch ab \
 && [ "$(find -type f | sort)" == $'./a\n./ab' ]

FROM top-aa AS top-aaa
RUN touch aaa \
 && [ "$(find -type f | sort)" == $'./a\n./aa\n./aaa' ]

FROM top-aa AS top-aab
RUN touch aab \
 && [ "$(find -type f | sort)" == $'./a\n./aa\n./aab' ]
