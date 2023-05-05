tplbuild: Templated Container Build Tool
========================================

`tplbuild` is a wrapper around
`Dockerfiles <https://docs.docker.com/engine/reference/builder/>`_
to make building container images better. The two main features that inspired
the creation of `tplbuild` were

- Templating build instructions through `Jinja
  <https://jinja.palletsprojects.com/en/latest/>`_
- Enabling fast and reproducible builds among developers

`tplbuild` can be configured against any image builder supporting the Dockerfile
syntax but it's recommended to use a builder among the list of officially
:ref:`supported builders <Builders>`.

.. raw:: html

    <div style="position: relative; padding-bottom: 56.25%; height: 0; overflow: hidden; max-width: 100%; height: auto;">
        <iframe src="https://www.youtube.com/embed/HDiyABr8Adw" frameborder="0" allowfullscreen style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;"></iframe>
    </div>

Installation
------------

`tplbuild` can be installed through `pip`. This installs both the
:code:`tplbuild` CLI utility and the `tplbuild` Python library.

.. code-block:: sh

  pip install tplbuild

`tplbuild` is supported and tested on Python 3.8-3.11

When should tplbuild be used?
-----------------------------

There are many reasons `tplbuild` might be the right tool for you. These
include:

- You have multiple images that share build logic
- You have multiple build profiles (e.g. dev/prod)
- There are multiple devs or machines building your images.
- You need the image environment to be reproducible across builds and builders
- You use CI steps that want to run in your container environment (e.g. lint)
- You need to enforce change management controls
- You want to publish multi-architecture images
- You need a process to manage `CVEs
  <https://en.wikipedia.org/wiki/Common_Vulnerabilities_and_Exposures>`_ in your images

`tplbuild` may not be the right tool for you if

- You are working alone
- Reproducible builds are not important
- You do not use Dockerfiles to build your container images
- You want to use a builder other than the officially :ref:`supported builders <Builders>`.
- You rely on other tools to build your images already that cannot be configured
  to use `tplbuild` (e.g. docker-compose build).

An example
----------

To better understand how `tplbuild` works let's look at a simple node
application and convert it into something managed by `tplbuild`. A
reasonable starting point for a Dockerfile might look like below:


.. code-block:: Dockerfile

  # Use node 18
  FROM node:18

  # Install application packages
  WORKDIR /my-app
  COPY package.json ./
  RUN npm install

  # Install application code
  COPY . .
  CMD ["node", "my-app.js"]


Source image locking
____________________

The very first instruction :code:`FROM node:18` instructs the builder
what image to begin with. `tplbuild` refers to these externally provided images
as "source" images. These *source images* will either be downloaded by the
builder or a cached version of the image will be used.

But what exactly is in the image "node:18"? It refers to version 18 of the
"node" image repository. However, it does not fully specify the contents. In
fact, repository maintainers will frequently re-tag images to pull in
minor/patch version changes or security updates (and this is good). However,
for the same reasons we use `lock files
<https://nodejs.dev/learn/the-package-lock-json-file>`_ at the application
package level, `tplbuild` "locks" the image digest for each *source image* so
the build will not *unexpectedly* change.

Without changing our Dockerfile we can get source image locking by using
`tplbuild`. Running :code:`tplbuild build` will build our image and
create a new file named .tplbuilddata.json. This file functions as `tplbuild's`
lock file. Within it you can see the image digest that we locked "node:18" to.
Future builds will reference this stored value and use the same digest even if
"node:18" is later updated. You can run :code:`tplbuild source-update` to forcibly
update your source images to the latest digests to pull in security updates when
needed.

Base images
___________

Let's look at the next three lines of our Dockerfile:

.. code-block:: Dockerfile

  WORKDIR /my-app
  COPY package.json ./
  RUN npm install --production

These are responsible for installing
our application's dependencies. This step could take awhile and
without the use of a node package lock could produce inconsistent results.
To fix this we can update our Dockerfile into two different
`build stages
<https://docs.docker.com/develop/develop-images/multistage-build/>`_:
The first stage we will call our "base" image and will contain all of our
applicataion's dependencies without our actual application code. The second
stage we'll call the "published" image and will be built on top of the *base
image*.  Our updated Dockerfile might look like below:

.. code-block:: Dockerfile

  # Start base image 
  FROM node:18 AS base-my-app

  WORKDIR /my-app
  COPY package.json ./
  RUN npm install

  # Start published image 
  FROM base-my-app AS my-app

  COPY . .
  CMD ["node", "my-app.js"]

`tplbuild` has two different build commands `build` and `base-build`. The former
builds all *published images* while the second builds and stores to a configurable
registry all *base images*. To get this to work with `tplbuild` we first need to
tell it what repository to store its cached *base images* in. To do so you need
to edit `tplbuild.yml` and add a key `base_image_repo` that points to the
desired location. For instance your tplbuild.yml might look like below:

.. code-block:: yaml
  :caption: tplbuild.yml

  base_image_name: myregistry.com/base-my-app

By caching *base images* into this shared image registry we only need to build
the *base image* once and allow any number of developers to share that work by
accessing this cached image.

Now you can build your base image using the command :code:`tplbuild base-build`. After
that has completed you can again look at `.tplbuilddata.json` and see the cached
base image digest along with a content hash of the base image. This content hash
reflects all the inputs that went into producing that base image including the
source image, build commands, and any files referenced in COPY instructions. If
you attempt to build base images again it will recognize that nothing has
changed and not rebuild. If you update "package.json" the content hash will
update and the base image will rebuild.

Once you have rebuilt the base image you can build the published image using the
same command as before, :code:`tplbuild build`.

Profiles
________

Now suppose we wanted to support a "dev" and "release" build of our image. After
all, we don't want our devlopment packages installed in our release image.
To support this `tplbuild` renders our Dockerfile as a Jinja templates allowing
us to vary our build logic depending on variables. We can
update our :code:`npm install` command to look like this instead:

.. code-block:: Dockerfile

  RUN npm install{% if vars.production %} --production{% endif %}


To define this `vars.production` flag we use "profiles". A profile is just a mapping
of key/value data that is passed to the Jinja template. We can add *default_profile* and
*profiles* configurations to our tplbuild.yml file to define this new flag.

.. code-block:: yaml
  :caption: tplbuild.yml

  default_profile: dev
  profiles:
    dev:
      production: false
    release:
      production: true

Now we can re-run :code:`tplbuild base-build` to build and store the base image for
every profile. When we run :code:`tplbuild build` it will build for only the default
profile. We can use the :code:`--profile release` flag to switch to our "release"
profile.

We could take this concept even further and produce images for multiple versions
of node. Perhaps we are writing a library and want to ensure it's well tested in
each of our supported environments. We could update the start of our base-image
to be

.. code-block:: Dockerfile
  
  FROM node:{{ vars.node_version }} AS base-my-app

And update our profiles to look like

.. code-block:: yaml

  default_profile: dev
  profiles:
    dev:
      production: false
      node_version: 18
    dev_14:
      production: false
      node_version: 14
    dev_16:
      production: false
      node_version: 16
    release:
      production: true
      node_version: 18


Now we can easily build and test our image in each of these environments with
locked source files and prebuilt base images.


Multi-Architecture
__________________

By default `tplbuild` uses the architecture that is native to the builder. If we
later want to build against multiple architectures and publish multi
architecture images `tplbuild` can help with that too. Support is added as
easily as listing the desired architectures in your `tplbuild.yml` file. For
example:

.. code-block:: yaml
  :caption: tplbuild.yml

  platforms:
    - linux/amd64
    - linux/arm64

Repeating our :code:`tplbuild base-build` operation will now build for every
combination of platform and profile. When using :code:`tplbuild build` by default the
native platform will be used of the builder. You can use the :code:`--platform`
flag to specify the platform you'd like to use.

Publishing Images
_________________

`tplbuild` can automatically publish your images to a registry. Unlike the
:code:`tplbuild build` command, :code:`tplbuild publish` will build against all platforms and
produce a multi-architecture image if needed. To use :code:`tplbuild publish` you
first need to configure where the image should be published. For instance you
could add the below line to your tplbuild.yml file.

.. code-block:: yaml
  :caption: tplbuild.yml

  stage_push_name: |
    msg555/{{ stage_name }}:{{ profile }}

Note that this (and several other fields in tplbuild.yml) is itself a Jinja
template to allow further customization. Now we can run :code:`tplbuild publish --profile release` and
it will push our multiarchitecture image to :code:`msg555/my-app:release`.


How does tplbuild work internally?
==================================

`tplbuild` works by minimally parsing the Dockerfile syntax to construct a build
graph. A `node` in this graph represents an image after some number of build
steps where an `edge` represents a single build step in the Dockerfile (e.g. a
:code:`RUN` or :code:`COPY` instruction). Using this build graph `tplbuild` can
do several things:

- Collect and resolve all referenced *source* and *base* images
- Compute a *content hash* of any image step

  - Allows `tplbuild` to know when a base image is out of date
  - Allows shared build work to be collapsed into a single node

- Allows build contexts to be sent once and shared if needed

Once all *source* and *base* images have been resolved, the build graph is sent
to the planner which breaks up the build into a series of builder invocations.
The planner seeks first to maximize the amount of shared build steps between
invocations while second minimizing the number of times the builder needs to be
called.

Finally, the build plan is sent to the executor which invokes the underlying
build client with the desired level of parallelism as the dependencies of each
build step complete. The executor may tag some intermediate images with a tag
of the form :code:`tplbuild-$UUID`. This is done to ensure the intermediate
image is not garbage collected by the builder until the build is complete. These
intermediate images will be removed when the build exits or is interrupted.

What Dockerfile features are not supported?
===========================================

`tplbuild` will never attempt to support customizable frontends in a general
sense (i.e. :code:`# syntax=frontend/image`). `tplbuild` will do its best to
parse the Dockerfile but it's possible syntax features enabled by the frontend
will not work as expected with `tplbuild`. For example, 
:code:`docker/dockerfile:1.3-labs` added support for heredocs that `tplbuild`
is not yet capable of parsing. As `tplbuild` matures, a list of officially
supported frontend features and versions will be published.

Glossary
========

There are several different types of images that `tplbuild` works with:

- Source images

  - Externally provided images (e.g. docker.io/ubuntu:22.04)
  - Locked to a fixed digest by `tplbuild`

- Base images

  - A shared image with project dependencies installed
  - Should be updated infrequently
  - Build once, share among all users

- Published image

  - The final product; an image you wish to use or publish

- Intermediate image

  - A partially built image produced as a byproduct of the build process. These
    will typically be cleaned up by `tplbuild`.

- Build stage

  - A Dockerfile can have multiple build stages. Each build stage begins with a
    :code:`FROM` instruction and has a corresponding name.
  - Published images and base images always correspond to a build stage.

- Build context

  - A special build stage containing file data sent to the builder.
  - Uses dockerignore syntax to control what files are sent.

.. _Builders:

Supported Builders
------------------

`tplbuild` currently officially supports the below builders.

- docker
- docker buildx
- podman

By default `tplbuild` will use the `docker` builder. You can configure
which builder you want to use by updating your :ref:`user config <UserConfig>`.


References
----------

.. toctree::
  :caption: User Manual

  cli
  rendering

.. toctree::
  :caption: Configuration Reference

  config
  
.. toctree::
  :caption: Library Reference

  library

.. toctree::
  :caption: Changelist
  :titlesonly:

  changelist/index

