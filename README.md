tplbuild is a work in progress, check back soon!


tplbuild is a templated reproducible container build tool.

* One templated build file for all your image configurations (e.g. "dev" or * "prod")
  * No more nearly the same build files
  * Full customization of docker ignore files per configuration
  * _Don't repeate yourself_ - Share common build logic between images
  * Templated with [Jinja](https://jinja.palletsprojects.com/), a popular Python templating language
  * Rendered build files are an extended versions of the standard [Dockerfile](https://docs.docker.com/engine/reference/builder/#format) format
* Support for _base_ images
  * Prebuild all your base images for every configuration in a single command
  * Lower build time for developer's
  * Enables _hermetic_ top-level image builds
  * Check if base images are up to date for CI
* Support for fixed _source images_
  * Update to the latest source image with a single command
* Base images and fixed source images enable reproducible builds
  * Ensures consistent environment among users
  * Ensures meaningful vulnerability scanning
* Automatically tag and push images as needed
* Support for multi-arch images


##### Sample tplbuild.yml

Here's an example of what a configuration file might look like for `tplbuild`.
This file tells `tplbuild` important information like what template
configurations there are, how to form the image build contexts, and what
platforms to build against. These fields are all optional and building without a
tplbuild.yml file at all can be done if just getting started.

```yaml
version: "1.0"

# Define how base images are named and where they are pushed. This is required
# if using base images in your build file.
base_image_name: docker.myorg.com/base-{stage_name}

# Define how to tag/push built top level images by default. What image tags to
# use can be fully customized per stage as well.
stage_image_name: msg555/{{ stage_name }}

# Some stuff that should probably be user specific.
# TODO: Decide how to manage project configuration with user configuration.
registry:
  ssl_context:
    insecure: false
    cafile: null
    capath: null

# List of platforms to build images for. This will default to [linux/amd64]
# but will generate a warning in all cases if unset. This is meant to reduce
# the amount of configuration to get started but long term projects should
# explicitly set the targetted platform list even if does match the default.
platforms:
  - linux/amd64
  - linux/arm64

# Define a mapping of template arguments for each build configuration you want
# to support.
default_profile: dev
profiles:
  dev:
    env: dev
    user: root
    my_tags:
      - myimage:latest
      - myimage:dev
  release:
    env: release
    user: www-data
    my_tags:
      - myimage:latest
    my_push_tags:
      - myimage:v1.0.2

# Defines the build contexts used in your images. If not present there will be
# a single build context named "default" that points to the root build path
# using the ignore patterns in the ".dockerignore" file if present.
contexts:
  # "default" is the build context that will be used in images that do not
  # eplicitly set their build context.
  default:
    base_dir: . # Optional, defaults to "."
    umask: '022' # Optional, defaults to 022. If set to null instead it will
                 # use the exact mode bits from the build context. Otherwise
                 # the user bits will be copied to the group/all bits and then
                 # reduced using the umask setting.

    # Set ignore patterns either by file or directly in the yaml. If using
    # a file that file itself will be rendered as a jinja file, passed the
    # same arguments passed to the Dockerfile rendering.
    # ignore_file: .dockerignore
    ignore: | # Set 
      *
      !src

  # Base images need to be updated any time their build instructions change or
  # a build context they depend on changes. Therefore it's good practice to use
  # a minimal build context for base images. For example this build context
  # ensures that we update the base images if and only if requirements.txt
  # changes.
  base:
    base_dir: .
    ignore: |
      *
      !requirements.txt
      {% if env == "dev" %}!requirements-dev.txt{% endif %}
```

##### Sample Dockerfile

```
# Define base image stage
FROM python:3.8 AS base-myimage
PUSHCONTEXT base

WORKDIR /work
COPY . ./
RUN pip install -r requirements.txt {% if env == "dev" -%}-r requirements-dev.txt{%- endif %}


# Define top level image stage.
FROM base-myimage AS myimage

COPY src ./mymodule
COMMAND ["python", "-m", "mymodule"]
```


##### Sample tplbuild usage


```
# Builds/tags/pushes all top-level images using the default configuration
tplbuild build

# Builds/pushes all base images for all configurations that are out of date
tplbuild base-build

# Checks that all base images are up to date, does not build anything. Intended
# for continuous integration checks.
tplbuild base-build --check

# Prints the repo and tag where a given base image is stored for the default
# configuration.
tplbuild base-lookup myimage

# Start a container using a base image
docker run -it --rm "$(tplbuild base-lookup myimage)"

# Update all source image manifest content addresses
tplbuild source-update

# Prints the repo@sha that is used for a specific source image
tplbuild source-lookup python:3.8
```
