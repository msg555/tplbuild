# tplbuild - Templated reproducible container build tool

*tplbuild* is a wrapper around 
[Dockerfiles](https://docs.docker.com/engine/reference/builder/#format)
to make buildilng container images better. The two main features that inspired
the creaton of *tplbuild* were

- Templating build instructions through [Jinja](https://jinja.palletsprojects.com/)
- Enabling fast and reproducible builds among developers

## Installation

*tplbuild* can be installed through *pip*. This installs both the `tplbuild`
CLI utility and the *tplbuild* Python library.

```sh
pip install tplbuild
```

*tplbuild* is supported and tested on Python 3.8-3.10


## Documentation

Documentation for *tplbuild* can be found
[here](https://tplbuild.readthedocs.io/)
