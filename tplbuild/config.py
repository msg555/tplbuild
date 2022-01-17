import os
from typing import Any, Dict, List, Literal, Optional

import pydantic

RESERVED_PROFILE_KEYS = {
    "begin_stage",
}


class TplContextConfig(pydantic.BaseModel):
    """
    Config model representing a build context.
    """

    #: The base directory (relative to the config base directory) of
    #:     the build context. This must be a relative path and cannot point
    #:     above the config base directory.
    base_dir: str = "."
    #: The umask as a three digit octal string. This may also be set to
    #:     None if the context permissions should be passed through directly.
    umask: Optional[str] = "022"
    #: The ignore_file to load patterns from. If this and :attr:`ignore`
    #:     are both None then this will attempt to load ".dockerignore", using
    #:     an empty list of patterns if that cannot be loaded.
    ignore_file: Optional[str] = None
    #: Ignore file string. If present this will be used over :attr:`ignore_file`.
    ignore: Optional[str] = None

    @pydantic.validator("umask")
    def umask_valid_octal(cls, v):
        """Ensure that umask is three-digit octal sequence"""
        if v is None:
            return v
        if 0 <= int(v, 8) <= 0o777:
            raise ValueError("umask out of range")
        return v

    @pydantic.validator("base_dir")
    def normalize_base_dir(cls, v):
        """Normalize the base directory"""
        return f".{os.path.sep}{os.path.normpath(os.path.join(os.path.sep, v))[1:]}"


class ClientConfig(pydantic.BaseModel):
    """
    Configuration of commands to perform various container operations. This is
    meant to be a generic interface that could plug into a variety of container
    build systems. The defaults are suitable for a vanilla docker build.
    """

    #: Build command arguments. The string {image} will be formatted with
    #: the desired target image for any part of the build command.
    build: List[str] = ["docker", "build", "--tag", "{image}", "-"]
    #: Tag command arguments. The string {source_image} and {target_image} will
    #: be formatted with the source_image and target_image respectively.
    tag: List[str] = ["docker", "tag", "{source_image}", "{target_image}"]
    #: Push command arguments. The string {image} will be formatted with the
    #: image that will be pushed.
    push: List[str] = ["docker", "push", "{image}"]
    #: Untag command arguments. The string {image} will be formatted with the
    #: image that should be untagged. This is necessary for anonymous build
    #: stages generated by tplbuild that carry a temporary tag to avoid being
    #: reclaimed by the underlying container engine.
    untag: List[str] = ["docker", "rmi", "{image}"]

    #: Maximum number of concurrent build jobs. If set to 0 this will be set to
    #: `os.cpu_count()`.
    build_jobs: int = 1
    #: Maximum number of concurrent push jobs.
    push_jobs: int = 4
    #: Maximum number of concurrent tag jobs.
    tag_jobs: int = 32

    @pydantic.validator("build_jobs")
    def build_jobs_valid(cls, v):
        """ensure build_jobs is non-negative"""
        if v == 0:
            return os.cpu_count()
        if v < 0:
            raise ValueError("build_jobs must be non-negative")
        return v

    @pydantic.validator("push_jobs")
    def push_jobs_valid(cls, v):
        """ensure push_jobs is positive"""
        if v <= 0:
            raise ValueError("push_jobs must be positive")
        return v

    @pydantic.validator("tag_jobs")
    def tag_jobs_valid(cls, v):
        """ensure tag_jobs is positive"""
        if v <= 0:
            raise ValueError("push_jobs must be positive")
        return v


class TplConfig(pydantic.BaseModel):
    """Top level config model for tplbuild"""

    #: Must be "1.0"
    version: Literal["1.0"] = "1.0"
    #: Image repo where base images will be stored. This will
    #:     be interpretted as a Python format string receiving the single
    #:     named argument "stage_name".
    base_image_repo: Optional[str] = None
    #: Syntax header to include in rendered dockerfiles. This is useful if you
    #: e.g. want to make use of buildkit features not available by default.
    dockerfile_syntax: Optional[str] = None
    #: Client commands to use to perform different container actions. By
    #: default this will use the standard docker interface. If you wish to
    #: use a different builder or supply additional arguments to the build
    #: this would be the place to do it.
    client: ClientConfig = ClientConfig()
    #: List of platforms to build images for. If not present only the
    #:     default platform will be used. Images will be built for each of the
    #:     platforms as an image manifest by default.
    platforms: Optional[List[str]] = None
    #: A mapping of profile names to string-key template arguments to pass
    #:     to any documents rendered through Jinja for each profile.
    profiles: Dict[str, Dict[str, Any]] = {}
    #: The name of the default profile to use. If this is empty
    #:     the first profile name from :attr:`profiles` will be used instead.
    default_profile: str = ""
    #: A set of named build context configurations. These contexts may
    #:     be referred to by name in the build file and should be unique
    #:     among all other stages.
    contexts: Dict[str, TplContextConfig] = {"default": TplContextConfig()}

    @pydantic.validator("profiles")
    def profile_name_nonempty(cls, v):
        """Make sure all profile names are non-empty"""
        if any(profile_name == "" for profile_name in v):
            raise ValueError("profile name cannot be empty")
        return v

    @pydantic.validator("profiles")
    def profile_reserved_keys(cls, v):
        """Make sure profile data does not use reserved keys"""
        for profile, profile_data in v.items():
            for reserved_key in RESERVED_PROFILE_KEYS:
                if reserved_key in profile_data:
                    raise ValueError(
                        f"Profile {repr(profile)} cannot have reserved key {repr(reserved_key)}"
                    )
        return v

    @pydantic.validator("default_profile")
    def default_profile_exists(cls, v, values):
        """Make sure default profile name exists if non-empty"""
        if v and v not in values["profiles"]:
            raise ValueError("default_profile must be a valid profile name")
        return v


class BuildData(pydantic.BaseModel):
    """
    Any build data that is managed by tplbuild itself rather than being
    configuration data provided by the user. Right now this includes a
    mapping of source images and base images to their content address
    sources.
    """

    #: Mapping of repo -> tag -> source image manifest hash.
    source: Dict[str, Dict[str, str]] = {}
    #: Mapping of profile -> stage_name -> cached base image content hash. This
    #: content hash is used to named the cached base image which is expected to
    #: be available/pullable by anyone using tplbuild for a given project. The
    #: content hash is taken as the non-symbolic hash of the base image build
    #: node, this is not the image's manifest hash as is stored for source
    #: images.
    base: Dict[str, Dict[str, str]] = {}
