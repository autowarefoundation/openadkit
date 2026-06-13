FROM ubuntu:22.04

ARG AWSIM_VERSION=v2.0.1
ARG AWSIM_ASSET=AWSIM-Demo-Lightweight.zip
# Optional: set to the expected SHA-256 of the AWSIM asset to verify the
# download. Left empty by default so the build works without pinning.
ARG AWSIM_SHA256=

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    libasound2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgl1 \
    libglib2.0-0 \
    libgtk-3-0 \
    libnss3 \
    libvulkan1 \
    libx11-6 \
    libxcursor1 \
    libxext6 \
    libxi6 \
    libxinerama1 \
    libxrandr2 \
    libxrender1 \
    libxss1 \
    unzip \
    xvfb \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/awsim

RUN curl -L --fail -A Mozilla/5.0 -o /tmp/awsim.zip "https://github.com/autowarefoundation/AWSIM/releases/download/${AWSIM_VERSION}/${AWSIM_ASSET}" \
  && if [ -n "${AWSIM_SHA256}" ]; then echo "${AWSIM_SHA256}  /tmp/awsim.zip" | sha256sum -c -; fi \
  && unzip -q /tmp/awsim.zip -d /opt/awsim \
  && chmod +x "$(find /opt/awsim -name 'AWSIM*.x86_64' -print -quit)" \
  && rm /tmp/awsim.zip

COPY awsim-entrypoint.sh /usr/local/bin/awsim-entrypoint.sh
RUN chmod +x /usr/local/bin/awsim-entrypoint.sh

ENTRYPOINT ["awsim-entrypoint.sh"]
