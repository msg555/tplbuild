{% from "Dockerfile.macros" import fibonacci with context %}

FROM anon-fib-10 AS fibonacci

{{ fibonacci(10) }}

CMD ["cat", "/result.txt"]
