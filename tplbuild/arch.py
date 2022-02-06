import platform
from typing import Tuple


def normalize_architecture(arch: str, variant: str) -> Tuple[str, str]:
    """
    Normalize the passed architecture and variant. This is copying the
    same semantics used in
    https://github.com/moby/containerd/blob/ambiguous-manifest-moby-20.10/platforms/database.go
    """
    arch, variant = arch.lower(), variant.lower()
    if arch == "i386":
        return "386", ""
    if arch in ("x86_64", "x86-64"):
        return ("amd64", "")
    if arch in ("aarch64", "arm64"):
        if variant in ("8", "v8"):
            variant = ""
        return "arm64", variant
    if arch == "armhf":
        return "arm", "v7"
    if arch == "armel":
        return "arm", "v6"
    if arch == "arm":
        if variant in ("", "7"):
            variant = "7"
        elif variant in ("5", "6", "8"):
            variant = f"v{variant}"
        return "arm", variant
    return arch, variant


def normalize_platform(os: str, arch: str, variant: str = "") -> str:
    """
    Like :meth:`normalize_architecture` except include the `os` and return
    the normalized platform string.
    """
    arch, variant = normalize_architecture(arch, variant)
    if variant:
        return f"{os}/{arch}/{variant}"
    return f"{os}/{arch}"


def split_platform(platfrm: str) -> Tuple[str, str, str]:
    """
    Split a platform string into its (os, architecture, variant) form.
    """
    parts = platfrm.split("/", maxsplit=2)
    return (
        parts[0],
        parts[1] if len(parts) > 1 else "",
        parts[2] if len(parts) > 2 else "",
    )


def normalize_platform_string(platform_str: str) -> str:
    """
    Normalize a platform string like 'linux/arm64/v8' into 'linux/arm64'.
    """
    parts = platform_str.split("/", maxsplit=2)
    if len(parts) == 1:
        return normalize_platform("linux", parts[0])
    return normalize_platform(*parts)


def client_platform(osname: str = "linux"):
    """
    Return the appropriate platform string for the client. This will ignore
    the local operating system and just use "linux" as the OS type as this
    is typically what is wanted.
    """
    return normalize_platform(osname, platform.machine(), "")
