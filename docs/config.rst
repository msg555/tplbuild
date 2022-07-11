
Configuration Reference
-----------------------

`tplbuild` has two main configuration files. The project configuration controls
how `tplbuild` interacts and behaves with a specific `tplbuild` project. It
should be included in source control and shared among all developers
on the project. The user configuration, on the other hand, controls user-level
configuration options like which builder to use, what level of parallelism to
build with, and how to authenticate with registries and is not shared.

.. _ProjectConfig:

Project Config
==============

A project can be configured by creating a file named `tplbuild.yml`. When
`tplbuild` is invoked it will look for this file in the current directory
to configure the current project. Very basic projects that just need source
image locks do not require a `tplbuild.yml` file. The schema for `tplbuild.yml`
is given by the :class:`tplbuild.config.TplConfig` model. An example
`tplbuild.yml` file is below:

.. code-block:: yaml
  :caption: tplbuild.yml

  # Must be version '1.0' (will be assumed to be latest if omitted)
  version: "1.0"

  # Define how base images are named and where they are pushed. This is required
  # if using base images in your build file.
  base_image_repo: docker.myorg.com/base-{stage_name}

  # Define how to tag top-level images.
  stage_image_name: "{{ stage_name }}"

  # Define how to publish top-level images to a registry.
  stage_push_name: msg555/{{ stage_name }}:{{ profile }}

  # List of platforms to build images for.
  platforms:
    - linux/amd64
    - linux/arm64

  # Define build profiles. Each profile can be any free-form yaml data that
  # will be made available to the Dockerfile Jinja template when rendering.
  default_profile: dev 
  profiles:
    dev:
      python_version: '3.8'
      install_dev: yes
    release:
      python_version: '3.8'
      install_dev: no

  # Control what file data is passed to the build.
  contexts:
    default:
      ignore: |
        *
        !myproject
        !requirements*

  # Control which stages are base images and how stages are tagged/pushed.
  # Usually you can just prefix your stage names with "base-" (or "base_")
  # to mark stages as base images. Similarly you can use "anon-" to mark an
  # image as non-base but also not meant to be tagged/pushed.
  stages:
    my-base-image:
      base: yes
    my-main-image:
      base: no

  # Configure where tplbuild will look for the entrypoint template and any
  # other templates referenced with include statements.
  template_paths:
    - build
    - build/lib

  # Define the main template entrypoint to render all stages
  template_entrypoint: Dockerfile
    

Full documentation of each field within the tplbuild configure file can be found
below:

.. autopydantic_model:: tplbuild.config.TplConfig

.. autopydantic_model:: tplbuild.config.TplContextConfig

.. autopydantic_model:: tplbuild.config.StageConfig

.. _UserConfig:

User Config
===========

The user configuration controls configuration options that are not specific to
a particular project like what builder backend to use. `tplbuild` will look for
a user configuration in the following places

- ~/.tplbuildconfig.yml
- .tplbuildconfig.yml

If multiple configuration files are present the top-level values of the later
configuration files will overwrite the earlier ones.

.. autopydantic_model:: tplbuild.config.UserConfig

.. autopydantic_model:: tplbuild.config.ClientConfig

.. autopydantic_model:: tplbuild.config.ClientCommand

.. autopydantic_model:: tplbuild.config.UserSSLContext
