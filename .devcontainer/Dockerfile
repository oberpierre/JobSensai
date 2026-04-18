# You can pick any Debian/Ubuntu-based image. 😊
FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04

# Options for setup script
ARG INSTALL_ZSH="true"
ARG UPGRADE_PACKAGES="false"
ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=$USER_UID
# Install needed packages and setup non-root user. Use a separate RUN statement to add your own dependencies.
COPY library-scripts/*.sh /tmp/library-scripts/
RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && /bin/bash /tmp/library-scripts/common-debian.sh "${INSTALL_ZSH}" "${USERNAME}" "${USER_UID}" "${USER_GID}" "${UPGRADE_PACKAGES}" "true" "true" \
    && apt-get install -y apt-transport-https curl gnupg

# Installing python 3.12 and pip
RUN apt-get install -y software-properties-common \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y python3.12 python3-pip \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1

# Install Bazel
ARG BAZEL_VERSION=8.4.2
ARG BAZEL_DOWNLOAD_SHA=dev-mode
RUN curl -fSsL -o /usr/local/bin/bazel https://github.com/bazelbuild/bazel/releases/download/${BAZEL_VERSION}/bazel-${BAZEL_VERSION}-linux-arm64 \
    && ([ "${BAZEL_DOWNLOAD_SHA}" = "dev-mode" ] || echo "${BAZEL_DOWNLOAD_SHA} */usr/local/bin/bazel" | sha256sum --check - ) \
    && chmod 0755 /usr/local/bin/bazel

# Install Aspect CLI
ARG ASPECT_CLI_VERSION=v2025.46.6
ARG ASPECT_CLI_DOWNLOAD_SHA=dev-mode
RUN curl -fSsL -o /usr/local/bin/aspect https://github.com/aspect-build/aspect-cli/releases/download/${ASPECT_CLI_VERSION}/aspect-launcher-aarch64-unknown-linux-musl \
    && ([ "${ASPECT_CLI_DOWNLOAD_SHA}" = "dev-mode" ] || echo "${ASPECT_CLI_DOWNLOAD_SHA} */usr/local/bin/aspect" | sha256sum --check - ) \
    && chmod 0755 /usr/local/bin/aspect

# Cleanup
RUN apt-get autoremove -y && apt-get clean -y && rm -rf /var/lib/apt/lists/* /tmp/library-scripts