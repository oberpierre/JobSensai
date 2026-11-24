"""Packages a py_binary and its runfiles as one gzip-compressed image layer."""

load("@aspect_bazel_lib//lib:tar.bzl", "mtree_mutate", "mtree_spec", "tar")
load("@aspect_bazel_lib//lib:transitions.bzl", "platform_transition_binary")

# The rules_python toolchain repo holding the hermetic interpreter, as Bazel names
# it inside a runfiles tree.
_INTERPRETER_REPO = "rules_python++python+python_3_12_x86_64-unknown-linux-gnu"

def py_entrypoint(binary_name):
    """The entrypoint running a py_binary's stub under its own hermetic interpreter.

    The base images carry no Python of their own, so the stub's shebang cannot
    resolve and the interpreter is named directly instead.

    Args:
        binary_name: the py_binary's name, which is also its basename under /app.

    Returns:
        the entrypoint as a list of strings.
    """
    return [
        "/app/{}.runfiles/{}/bin/python3".format(binary_name, _INTERPRETER_REPO),
        "/app/{}".format(binary_name),
    ]

def py_app_layer(name, binary, target_platform):
    """Defines `name`, a .tar.gz of `binary` and its runfiles under /app.

    The binary is built for `target_platform`. The interpreter's unused parts
    are pruned by prune_interpreter.awk.

    Args:
        name: the layer target's name.
        binary: the py_binary label to package.
        target_platform: the platform the binary is built for.
    """
    platform_transition_binary(
        name = name + "_binary",
        binary = binary,
        target_platform = target_platform,
    )

    mtree_spec(
        name = name + "_mtree",
        srcs = [name + "_binary"],
        include_runfiles = True,
    )

    mtree_mutate(
        name = name + "_mtree_app",
        mtree = name + "_mtree",
        strip_prefix = "{}/{}_binary".format(native.package_name(), name),
        package_dir = "app",
        includes = [Label(":prune_interpreter.awk")],
    )

    tar(
        name = name,
        srcs = [name + "_binary"],
        mtree = name + "_mtree_app",
        compress = "gzip",
    )
