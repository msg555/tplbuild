
Command Line Reference
----------------------

`tplbuild` is intended to be used through its command line interface. After
installing `tplbuild` with `pip` you can use the `tplbuild` CLI through the
:code:`tplbuild` entrypoint or using :code:`python -m tplbuild`. The rest of
this documentation will use the former. Each subcommand will explain how the
subcommand is expected to be used along with sample invocations. For more
details on each subcommand use the :code:`--help` flag.

Build
=====

Build some or all top-level images for a given profile and platform.
This is useful when building images to use/test locally.

Sample invocations:

.. code-block:: sh
  :caption: Build all top-level images for default profile and platform

  tplbuild build

.. code-block:: sh
  :caption: Build just `my-image` under the `dev` platform for `linux/amd64`

  tplbuild build --profile dev --platform linux/amd64 my-image


Publish
=======

Publish some or all top-level images for a given profile to their configured
repository. By default this will build each image for every configured platform
and push a multi-architecture image. Any image without a repository configured
will be ignored.

Sample invocations

.. code-block:: sh
  :caption: Publish all top-level images for default profile on every platform

  tplbuild publish

.. code-block:: sh
  :caption: Publish just `my-image` for `dev` profile on `linux/amd64` and `linux/arm64`

  tplbuild publish --profile dev --platform linux/amd64 --platform linux/arm64 my-image


Base Build
==========

Build out-of-date base images and push them to the configured repository.
Typically this will be invoked without any
arguments to rebuild any base images that are out of date.
If needed, additional flags can limit the profiles, platforms, and images
that are built. This is useful primarily when testing changes.

.. code-block:: sh
  :caption: Rebuild all out of date base images

  tplbuild base-build

.. code-block:: sh
  :caption: Check that all base images are up to date (for CI)

  tplbuild base-build --check

.. code-block:: sh
  :caption: Rebuild just `base-my-image` for `dev` profile on `linux/amd64`

  tplbuild base-build --profile dev --platform linux/amd64 base-my-image

.. code-block:: sh
  :caption: Update source images and force rebuild all base images

  tplbuild base-build --update-salt --update-sources

Base Lookup
===========

Print the full name of the requested base image. This is useful if you want to
use the base image directly (for instance to do linting without building any
top-level images).

.. code-block:: sh
  :caption: Print image name of `base-my-image` for default profile and platform

  tplbuild base-lookup base-my-image

.. code-block:: sh
  :caption: Print full image name of `base-my-image` for `dev` profile and `linux/amd64` platform

  tplbuild base-lookup --profile dev --platform linux/amd64 base-my-image

Source Update
=============

This sub-command is used to explicitly update the locked source image digets to
the latest digest available in each of their repositories. It is recommended to
run this update at a regular interval (e.g. once a week) to ensure that
upstream security updates eventually make their way into your project.

.. code-block:: sh
  :caption: Update all source image digests

  tplbuild source-update

.. code-block:: sh
  :caption: Update only source image `node:18`

  tplbuild source-update node:18

Source Lookup
=============

Print the full name with digest of the requested source image.

.. code-block:: sh
  :caption: Print the full name with digest of the `node:18` source image being used

  tplbuild source-lookup node:18
