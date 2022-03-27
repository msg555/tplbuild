import os
import ssl
import uuid
from typing import Any, Dict, List, Literal, Optional

import pydantic

from .utils import format_simple

RESERVED_PROFILE_KEYS = {
    "begin_stage",
    "platform",
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


def _validate_command(cmd: "ClientCommand", params: List[str]) -> "ClientCommand":
    """Helper function to validate command format strings"""
    params_dict = {key: "" for key in params}
    try:
        cmd.render_args(params_dict)
    except KeyError as exc:
        raise ValueError("command args format invalid: str(exc)") from exc
    try:
        cmd.render_environment(params_dict)
    except KeyError as exc:
        raise ValueError("command environment format invalid: str(exc)") from exc
    return cmd


class ClientCommand(pydantic.BaseModel):
    """
    Configuration to invoke an external build command.

    Typically both :attr:`args` and the values of :attr:`environment` will be
    subject to keyword substitutions. For instance build commands will substitute
    any instance of the string "{image}" with the desired image tag. This is to
    be similar to the typical Python format implementation (although does not
    use `str.format` for security reasons).
    """

    #: Command and additional arguments to execute to perform the command.
    args: List[str]
    #: Additional environmental variables to pass to the command.
    environment: Dict[str, str] = {}

    def render_args(
        self,
        params: Dict[str, str],
    ) -> List[str]:
        """Return the list of arguments after being rendered with the given params"""
        return [format_simple(arg, **params) for arg in self.args]

    def render_environment(self, params: Dict[str, str]) -> Dict[str, str]:
        """Return the environment after being rendered with the given params"""
        return {
            key: format_simple(val, **params) for key, val in self.environment.items()
        }


class ClientConfig(pydantic.BaseModel):
    """
    Configuration of commands to perform various container operations. This is
    meant to be a generic interface that could plug into a variety of container
    build systems. The defaults are suitable for a vanilla docker build.
    """

    #: Build command config. Arguments and environment values will
    #: be formatted with `image` as the desired build tag.
    build: ClientCommand
    #: Platform aware build command config. Arguments and environment
    #: values will be formatted with `image` as the desired build tag
    #: and `platform` as the desired build platform. This must be configured
    #: when doing platform aware builds.
    build_platform: Optional[ClientCommand] = None
    #: Tag command config. Arguments and evnrionment values will be
    #: formatted with `source_image` and `target_image` as the source
    #: and target tag names, respectively.
    tag: ClientCommand
    #: Pull command config. Arguments and environment values will be
    #: formatted with `image` as the desired push image. If present
    #: this command will be used to explicitly pull images and will be subject
    #: to the same concurrency pool as push operations. Without this command
    #: pulling images will be up to the builder which can lead to many
    #: concurrent pulls potentially being rate limited by the registry.
    pull: Optional[ClientCommand] = None
    #: Push command config. Arguments and environment values will be
    #: formatted with `image` as the desired push image.
    push: ClientCommand
    #: Untag command config. Arguments and environment values will be
    #: formatted with `image` as the desired tag to remove. This is
    #: necessary for anonymous build stages generated by tplbuild that
    #: carry a temporary tag to avoid being reclaimed by the underlying
    #: container engine during a build.
    untag: ClientCommand
    #: Print the default build platform. If this is not set then the
    #: default build platform will be calculated using the local
    #: client platform instead. The output will be normalized to convert
    #: e.g. "linux/x64_64" to "linux/amd64". Will not be used for
    #: non-platform aware build configurations.
    platform: Optional[ClientCommand] = None

    @pydantic.validator("build")
    def build_cmd_valid(cls, v):
        """Make sure build command is valid"""
        return _validate_command(v, ["image"])

    @pydantic.validator("build_platform")
    def build_platform_cmd_valid(cls, v):
        """Make sure build platform command is valid"""
        if v is None:
            return v
        return _validate_command(v, ["image", "platform"])

    @pydantic.validator("tag")
    def tag_cmd_valid(cls, v):
        """Make sure tag command is valid"""
        return _validate_command(v, ["source_image", "target_image"])

    @pydantic.validator("pull")
    def pull_cmd_valid(cls, v):
        """Make sure pull command is valid"""
        if v is None:
            return v
        return _validate_command(v, ["image"])

    @pydantic.validator("push")
    def push_cmd_valid(cls, v):
        """Make sure push command is valid"""
        return _validate_command(v, ["image"])

    @pydantic.validator("untag")
    def untag_cmd_valid(cls, v):
        """Make sure untag command is valid"""
        return _validate_command(v, ["image"])

    @pydantic.validator("platform")
    def platform_cmd_valid(cls, v):
        """Make sure platform command is valid"""
        if v is None:
            return v
        return _validate_command(v, [])


UNSET_CLIENT_CONFIG = ClientConfig(
    build=ClientCommand(args=[]),
    tag=ClientCommand(args=[]),
    push=ClientCommand(args=[]),
    untag=ClientCommand(args=[]),
)
DOCKER_CLIENT_CONFIG = ClientConfig(
    build=ClientCommand(
        args=["docker", "build", "--tag", "{image}", "-"],
    ),
    build_platform=ClientCommand(
        args=["docker", "build", "--tag", "{image}", "-"],
        environment={
            "DOCKER_DEFAULT_PLATFORM": "{platform}",
        },
    ),
    tag=ClientCommand(
        args=["docker", "tag", "{source_image}", "{target_image}"],
    ),
    pull=ClientCommand(
        args=["docker", "pull", "{image}"],
    ),
    push=ClientCommand(
        args=["docker", "push", "{image}"],
    ),
    untag=ClientCommand(
        args=["docker", "rmi", "{image}"],
    ),
    platform=ClientCommand(
        args=[
            "docker",
            "info",
            "--format",
            "{{{{ .OSType }}}}/{{{{ .Architecture }}}}",
        ],
    ),
)
# build_platform makes podman incorrectly not allow build contexts to be
# shared across architectures so is intentionally omitted here.
PODMAN_CLIENT_CONFIG = ClientConfig(
    build=ClientCommand(
        args=["podman", "build", "--tag", "{image}", "-"],
    ),
    tag=ClientCommand(
        args=["podman", "tag", "{source_image}", "{target_image}"],
    ),
    pull=ClientCommand(
        args=["podman", "pull", "{image}"],
    ),
    push=ClientCommand(
        args=["podman", "push", "{image}"],
    ),
    untag=ClientCommand(
        args=["podman", "rmi", "{image}"],
    ),
    platform=ClientCommand(
        args=[
            "podman",
            "info",
            "--format",
            "{{{{ .Version.OsArch }}}}",
        ],
    ),
)


class UserSSLContext(pydantic.BaseModel):
    """Custom SSL context used to contact registries"""

    #: Disable SSL/TLS verification
    insecure: bool = False
    #: File path to load CA certificates to trust.
    cafile: Optional[str] = None
    #: Folder container CA certificate files to trust.
    capath: Optional[str] = None
    #: Raw certificate data to trust.
    cadata: Optional[str] = None
    #: If True default system certs will be loaded in addition to any certs
    #: implied by `cafile`, `capath`, or `cadata`. Normally these will only be
    #: loaded if those are all unset.
    load_default_certs: bool = False

    def create_context(self) -> ssl.SSLContext:
        """Returns a SSLContext constructed from the passed options"""
        ctx = ssl.create_default_context(
            cafile=self.cafile,
            capath=self.capath,
            cadata=self.cadata,
        )
        if self.insecure:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        if self.load_default_certs:
            ctx.load_default_certs()
        return ctx


class StageConfig(pydantic.BaseModel):
    """Configuration data for a named build stage"""

    #: Is the stage a base stage
    base: bool = False
    #: All image names to assign to the built image. Must be empty for base images.
    image_names: List[str] = []
    #: All image names to assign and then push to remote registries.
    #: Must be empty for base images.
    push_names: List[str] = []

    @pydantic.validator("image_names")
    def image_names_empty_for_base(cls, v, values):
        """Ensure base images have no image_names"""
        if v and values["base"]:
            raise ValueError("image_names must be empty for base images")
        return v

    @pydantic.validator("push_names")
    def push_names_empty_for_base(cls, v, values):
        """Ensure base images have no push_names"""
        if v and values["base"]:
            raise ValueError("push_names must be empty for base images")
        return v


class UserConfig(pydantic.BaseModel):
    """User settings controlling tplbuild behavior"""

    #: Must be "1.0"
    version: Literal["1.0"] = "1.0"
    #: If :attr:`client` is None this field will be used to set the client
    #: configuration. Supported values are currently "docker" and "podman".
    #: If :attr:`client` is not None this field is ignored.
    client_type: Literal["docker", "podman"] = "docker"
    #: Client commands to use to perform different container actions. If unset
    #: a default configuration will be provided based on the value of
    #: :attr:`client_type`. If you wish to use a different builder or supply
    #: additional arguments to the build this would be the place to do it.
    client: ClientConfig = UNSET_CLIENT_CONFIG
    #: Maximum number of concurrent build jbs. If set to 0 this will be set to
    #: `os.cpu_count()`.
    build_jobs: int = 0
    #: Maximum number of concurrent push jobs.
    push_jobs: int = 4
    #: Maximum number of concurrent tag jobs.
    tag_jobs: int = 8
    #: Configure the SSL context used to contact registries. This only controls
    #: accesses made by tplbuild itself. The client builder will need to be
    #: configured separately.
    ssl_context: UserSSLContext = UserSSLContext()
    #: The path to the container auth configuration file to use when contacting
    #: registries. By default this will check the default search paths and conform
    #: to the syntax described in
    #: https://github.com/containers/image/blob/main/docs/containers-auth.json.5.md.
    auth_file: Optional[str] = None

    @pydantic.validator("build_jobs", always=True)
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

    @pydantic.validator("client", always=True)
    def default_replace_client(cls, v, values):
        """replace client with client_type if unset"""
        if v.build.args:
            return v
        if values["client_type"] == "docker":
            return DOCKER_CLIENT_CONFIG
        if values["client_type"] == "podman":
            return PODMAN_CLIENT_CONFIG
        raise ValueError("unexpected client_type")


class TplConfig(pydantic.BaseModel):
    """Configuration settings for a single tplbuild project"""

    #: Must be "1.0"
    version: Literal["1.0"] = "1.0"
    #: Jinja template that renders to the image name where a base image
    #: will be stored. This should *not* include a tag as tplbuild uses
    #: the tag itself to identify the content-addressed build. This
    #: template is passed "stage_name", "profile", and "platform"
    #: corresponding to the name of the stage, the name of the profile
    #: that rendered the image, and the name of the build platform respectively.
    base_image_name: Optional[str] = None
    #: A Jinja template that renders to the default image name for a
    #: given stage_name. Like :attr:`base_image_name` the template is passed
    #: "stage_name", "profile", "and "platform" parameters.
    stage_image_name: str = "{{ stage_name}}"
    #: A Jinja template that renders to the default push name for a
    #: given stage_name. Like :attr:`base_image_name` the template is passed
    #: "stage_name", "profile", "and "platform" parameters.
    stage_push_name: str = "{{ stage_name}}"
    #: List of platforms to build images for. This defaults to linux/amd64
    #:     but should be explicitly configured. Base images will be built
    #:     for each platform listed here allowing for top-level images to
    #:     be built in any of those platforms or as manifest lists when
    #:     pushed.
    platforms: List[str] = ["linux/amd64"]
    #: A mapping of profile names to string-key template arguments to pass
    #:     to any documents rendered through Jinja for each profile. Defaults
    #:     to a single empty profile named 'default'.
    profiles: Dict[str, Dict[str, Any]] = {"default": {}}
    #: The name of the default profile to use. If this is empty
    #:     the first profile name from :attr:`profiles` will be used instead.
    default_profile: str = ""
    #: A set of named build context configurations. These contexts may
    #:     be referred to by name in the build file and should be unique
    #:     among all other stages.
    contexts: Dict[str, TplContextConfig] = {"default": TplContextConfig()}
    #: A mapping of stage names to stage configs. This can be used to override
    #: the default behavior of tplbuild or apply different or more than just a
    #: single image name to a given stage. See
    #: :meth:`Tplbuild.default_stage_config` for information about default stage
    #: configuration.
    stages: Dict[str, StageConfig] = {}

    @pydantic.validator("platforms")
    def platform_nonempty(cls, v):
        """Ensure that platforms is non empty"""
        if not v:
            raise ValueError("platforms cannot be empty")
        return v

    @pydantic.validator("profiles")
    def profile_not_empty(cls, v):
        """Make sure there is at least one profile"""
        if not v:
            raise ValueError("profiles cannot be empty")
        return v

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

    #: Mapping of repo -> tag -> platform -> source image manifest digest.
    source: Dict[str, Dict[str, Dict[str, str]]] = {}
    #: Mapping of profile -> stage_name -> platform -> cached base image
    #: content hash. The content hash is taken as the non-symbolic hash of
    #: the base image build node.
    base: Dict[str, Dict[str, Dict[str, str]]] = {}
    #: A string combined with the base image definition hashes to produce
    #: the final hash for base images. This ensures that different projects
    #: use disjoint hash spaces, that the base image keys bear no information
    #: by themselves, and to force rebuilds by changing the salt.
    hash_salt: str = ""

    @pydantic.validator("hash_salt", always=True)
    def default_profile_exists(cls, v):
        """Fill in hash salt if not set"""
        if not v:
            return str(uuid.uuid4())
        return v
