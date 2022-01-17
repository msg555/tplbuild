import platform
from typing import Tuple


def client_platform(osname: str = "linux"):
    """
    Return the appropriate platform string for the client. This will ignore
    the local operating system and just use "linux" as the OS type as this
    is typically what is wanted.
    """
    osname = "linux"
    arch, variant = normalize_architecture(platform.machine(), "")
    if variant:
        return f"{osname}/{arch}/{variant}"
    return f"{osname}/{arch}"


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
