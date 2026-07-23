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

# The tool downloads select their artifact by the build host's architecture so the
# devcontainer builds on both amd64 and arm64. Each tool has a per-arch checksum
# (dev-mode skips verification for a bare `docker build`; compose passes the real ones).

# Install Bazel
ARG BAZEL_VERSION=8.4.2
ARG BAZEL_SHA_AMD64=dev-mode
ARG BAZEL_SHA_ARM64=dev-mode
RUN set -eu; \
    case "$(dpkg --print-architecture)" in \
      amd64) suffix=linux-x86_64; sha="${BAZEL_SHA_AMD64}" ;; \
      arm64) suffix=linux-arm64;  sha="${BAZEL_SHA_ARM64}" ;; \
      *) echo "unsupported architecture: $(dpkg --print-architecture)" >&2; exit 1 ;; \
    esac; \
    curl -fSsL -o /usr/local/bin/bazel "https://github.com/bazelbuild/bazel/releases/download/${BAZEL_VERSION}/bazel-${BAZEL_VERSION}-${suffix}"; \
    { [ "$sha" = dev-mode ] || echo "$sha */usr/local/bin/bazel" | sha256sum --check -; }; \
    chmod 0755 /usr/local/bin/bazel

# Install Aspect CLI
ARG ASPECT_CLI_VERSION=v2025.46.6
ARG ASPECT_CLI_SHA_AMD64=dev-mode
ARG ASPECT_CLI_SHA_ARM64=dev-mode
RUN set -eu; \
    case "$(dpkg --print-architecture)" in \
      amd64) suffix=x86_64-unknown-linux-musl;  sha="${ASPECT_CLI_SHA_AMD64}" ;; \
      arm64) suffix=aarch64-unknown-linux-musl; sha="${ASPECT_CLI_SHA_ARM64}" ;; \
      *) echo "unsupported architecture: $(dpkg --print-architecture)" >&2; exit 1 ;; \
    esac; \
    curl -fSsL -o /usr/local/bin/aspect "https://github.com/aspect-build/aspect-cli/releases/download/${ASPECT_CLI_VERSION}/aspect-launcher-${suffix}"; \
    { [ "$sha" = dev-mode ] || echo "$sha */usr/local/bin/aspect" | sha256sum --check -; }; \
    chmod 0755 /usr/local/bin/aspect

# Install gh CLI
ARG GH_VERSION=2.96.0
ARG GH_SHA_AMD64=dev-mode
ARG GH_SHA_ARM64=dev-mode
RUN set -eu; \
    case "$(dpkg --print-architecture)" in \
      amd64) gharch=amd64; sha="${GH_SHA_AMD64}" ;; \
      arm64) gharch=arm64; sha="${GH_SHA_ARM64}" ;; \
      *) echo "unsupported architecture: $(dpkg --print-architecture)" >&2; exit 1 ;; \
    esac; \
    curl -fSsL -o /tmp/gh.tar.gz "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${gharch}.tar.gz"; \
    { [ "$sha" = dev-mode ] || echo "$sha */tmp/gh.tar.gz" | sha256sum --check -; }; \
    tar -xzf /tmp/gh.tar.gz -C /tmp; \
    mv "/tmp/gh_${GH_VERSION}_linux_${gharch}/bin/gh" /usr/local/bin/gh; \
    chmod 0755 /usr/local/bin/gh; \
    rm -rf /tmp/gh.tar.gz "/tmp/gh_${GH_VERSION}_linux_${gharch}"

# Cleanup
RUN apt-get autoremove -y && apt-get clean -y && rm -rf /var/lib/apt/lists/* /tmp/library-scripts