tplbuild is a work in progress, check back soon!


tplbuild is a templated container build tool.

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
* Support for fixed _source images_
  * Update to the latest source image with a single command
* Base images and fixed source images enable reproducible builds
  * Ensures consistent environment among users
  * Ensures meaningful vulnerability scanning
* Automatically tag and push images as needed
* Support for multi-arch images
