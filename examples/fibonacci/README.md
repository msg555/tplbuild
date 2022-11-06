## Fibonacci

This is a toy example to demonstrate how macros can be used. More common usage
of macros would be to encapsulate common tasks like installing an OS dependency.

In this example we have a `fibonacci` macro that defines a new `anon-fib-n`
stage that will write the result of `fib(n)` to `/result.txt` using the results
from the `fibonacci(n-1)` and `fibonacci(n-2)` stages.

This also demonstrates how the `tplbuild` specific `END` command can be used to
manipulate the image stack.
