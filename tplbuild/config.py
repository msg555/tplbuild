import os
from typing import Any, Dict, List, Literal, Optional

import pydantic


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


class TplConfig(pydantic.BaseModel):
    """
    Top level config model for tplbuild.

    Attributes:
    """

    #: Must be "1.0"
    version: Literal["1.0"] = "1.0"
    #: Image repo where base images will be stored. This will
    #:     be interpretted as a Python format string receiving the single
    #:     named argument "stage_name".
    base_image_repo: Optional[str] = None
    #: List of platforms to build images for. If not present only the
    #:     default platform will be used. Images will be built for each of the
    #:     platforms as an image manifest by default.
    platforms: Optional[List[str]] = None
    #: The name of the default config to use. If this is not set
    #:     or refers to a non-existant config name the first config name from
    #:     :attr:`configs` will be used instead.
    default_config: Optional[str] = None
    #: A mapping of config names to string-key template arguments to pass
    #:     to any documents rendered through Jinja for this config.
    configs: Dict[str, Dict[str, Any]] = {}
    #: A set of named build context configurations. These contexts may
    #:     be referred to by name in the build file and should be unique
    #:     among all other stages.
    contexts: Dict[str, TplContextConfig] = {"default": TplContextConfig()}
